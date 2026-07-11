"""DynamoDB data layer (single-table, on-demand).

Table design (PK / SK):
  USER#<email>      PROFILE          user profile + wallet balance (paise)
  USER#<email>      KEY#<key_id>     API token metadata (hash, counters)
  SESSION#<sid>     META             chat session (owner, fees, token counters)
  SESSION#<sid>     MSG#<seq>        chat message
  ORDER#<order_id>  META             Razorpay payment record

GSI1 (GSI1PK) is used only to resolve an API token hash to its key item.

Wallet integrity: balance changes use atomic UpdateItem with condition
expressions, so concurrent charges can never overdraw.

Local development: set DYNAMODB_ENDPOINT_URL to a DynamoDB Local / moto
endpoint; the table is auto-created there.
"""

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from . import config


class InsufficientBalance(Exception):
    def __init__(self, needed_units: int, balance_units: int = -1):
        self.needed_units = needed_units
        self.balance_units = balance_units
        super().__init__("Insufficient balance: need %d units" % needed_units)


_table = None


def table():
    global _table
    if _table is None:
        kwargs = {"region_name": config.AWS_REGION}
        if config.DYNAMODB_ENDPOINT_URL:
            kwargs["endpoint_url"] = config.DYNAMODB_ENDPOINT_URL
        resource = boto3.resource("dynamodb", **kwargs)
        if config.DYNAMODB_ENDPOINT_URL:
            _ensure_local_table(resource)
        _table = resource.Table(config.DYNAMODB_TABLE)
    return _table


def _ensure_local_table(resource) -> None:
    """Create the table when running against DynamoDB Local / moto."""
    try:
        resource.meta.client.describe_table(TableName=config.DYNAMODB_TABLE)
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    resource.create_table(
        TableName=config.DYNAMODB_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "GSI1",
            "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
    )
    resource.meta.client.get_waiter("table_exists").wait(TableName=config.DYNAMODB_TABLE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seq() -> str:
    return "%020d#%s" % (time.time_ns(), uuid.uuid4().hex[:6])


def _plain(item: Optional[Dict]) -> Optional[Dict]:
    """Convert DynamoDB Decimals to int/float for JSON friendliness."""
    if item is None:
        return None
    out = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = int(v) if v == v.to_integral_value() else float(v)
        else:
            out[k] = v
    return out


# ---------------- Users & wallet ----------------

def create_user(email: str, password_hash: str, verified: bool = True) -> Optional[Dict]:
    item = {
        "PK": "USER#" + email, "SK": "PROFILE",
        "email": email, "password_hash": password_hash, "verified": verified,
        "balance_units": 0, "birth_details": None, "created_at": _now(),
    }
    try:
        table().put_item(Item=item,
                         ConditionExpression="attribute_not_exists(PK)")
        return item
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None  # already exists
        raise


def get_user(email: str) -> Optional[Dict]:
    resp = table().get_item(Key={"PK": "USER#" + email, "SK": "PROFILE"})
    return _plain(resp.get("Item"))


def update_user(email: str, **fields) -> None:
    expr = ", ".join("#f%d = :v%d" % (i, i) for i in range(len(fields)))
    names = {"#f%d" % i: k for i, k in enumerate(fields)}
    values = {":v%d" % i: v for i, v in enumerate(fields.values())}
    table().update_item(
        Key={"PK": "USER#" + email, "SK": "PROFILE"},
        UpdateExpression="SET " + expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def adjust_balance(email: str, delta_units: int) -> int:
    """Atomically add delta (may be negative). Never allows overdraw."""
    key = {"PK": "USER#" + email, "SK": "PROFILE"}
    try:
        if delta_units < 0:
            resp = table().update_item(
                Key=key,
                UpdateExpression="ADD balance_units :d",
                ConditionExpression="balance_units >= :need",
                ExpressionAttributeValues={
                    ":d": Decimal(delta_units), ":need": Decimal(-delta_units)},
                ReturnValues="UPDATED_NEW",
            )
        else:
            resp = table().update_item(
                Key=key,
                UpdateExpression="ADD balance_units :d",
                ExpressionAttributeValues={":d": Decimal(delta_units)},
                ReturnValues="UPDATED_NEW",
            )
        return int(resp["Attributes"]["balance_units"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            user = get_user(email)
            raise InsufficientBalance(-delta_units,
                                      user["balance_units"] if user else 0)
        raise


# ---------------- API keys ----------------

def create_api_key(email: str, name: str, prefix: str, key_hash: str) -> Dict:
    key_id = uuid.uuid4().hex[:12]
    item = {
        "PK": "USER#" + email, "SK": "KEY#" + key_id,
        "GSI1PK": "KEYHASH#" + key_hash,
        "key_id": key_id, "email": email, "name": name, "prefix": prefix,
        "key_hash": key_hash, "active": True, "calls": 0, "spent_units": 0,
        "created_at": _now(), "last_used_at": None,
    }
    table().put_item(Item=item)
    return item


def get_key_by_hash(key_hash: str) -> Optional[Dict]:
    resp = table().query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :h",
        ExpressionAttributeValues={":h": "KEYHASH#" + key_hash},
        Limit=1,
    )
    items = resp.get("Items", [])
    return _plain(items[0]) if items else None


def list_api_keys(email: str) -> List[Dict]:
    resp = table().query(
        KeyConditionExpression="PK = :p AND begins_with(SK, :s)",
        ExpressionAttributeValues={":p": "USER#" + email, ":s": "KEY#"},
    )
    return [_plain(i) for i in resp.get("Items", [])]


def revoke_api_key(email: str, key_id: str) -> Optional[Dict]:
    try:
        resp = table().update_item(
            Key={"PK": "USER#" + email, "SK": "KEY#" + key_id},
            UpdateExpression="SET active = :f REMOVE GSI1PK",
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeValues={":f": False},
            ReturnValues="ALL_NEW",
        )
        return _plain(resp["Attributes"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def record_key_usage(email: str, key_id: str, fee_units: int) -> None:
    table().update_item(
        Key={"PK": "USER#" + email, "SK": "KEY#" + key_id},
        UpdateExpression="ADD calls :one, spent_units :fee SET last_used_at = :t",
        ExpressionAttributeValues={
            ":one": Decimal(1), ":fee": Decimal(fee_units), ":t": _now()},
    )


# ---------------- Chat sessions & messages ----------------

def create_session(email: str, fee_units: int) -> Dict:
    sid = uuid.uuid4().hex[:16]
    item = {
        "PK": "SESSION#" + sid, "SK": "META",
        "session_id": sid, "email": email,
        "session_fee_units": fee_units, "usage_cost_units": 0,
        "input_tokens": 0, "output_tokens": 0, "created_at": _now(),
    }
    table().put_item(Item=item)
    return item


def get_session(sid: str) -> Optional[Dict]:
    resp = table().get_item(Key={"PK": "SESSION#" + sid, "SK": "META"})
    return _plain(resp.get("Item"))


def record_session_usage(sid: str, charge_units: int,
                         input_tokens: int, output_tokens: int) -> None:
    table().update_item(
        Key={"PK": "SESSION#" + sid, "SK": "META"},
        UpdateExpression=("ADD usage_cost_units :c, input_tokens :i, "
                          "output_tokens :o"),
        ExpressionAttributeValues={
            ":c": Decimal(charge_units), ":i": Decimal(input_tokens),
            ":o": Decimal(output_tokens)},
    )


def add_message(sid: str, role: str, content: str, input_tokens: int = 0,
                output_tokens: int = 0, charge_units: int = 0) -> None:
    table().put_item(Item={
        "PK": "SESSION#" + sid, "SK": "MSG#" + _seq(),
        "role": role, "content": content,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "charge_units": charge_units, "created_at": _now(),
    })


def list_messages(sid: str) -> List[Dict]:
    resp = table().query(
        KeyConditionExpression="PK = :p AND begins_with(SK, :s)",
        ExpressionAttributeValues={":p": "SESSION#" + sid, ":s": "MSG#"},
        ScanIndexForward=True,
    )
    return [_plain(i) for i in resp.get("Items", [])]


# ---------------- Payments ----------------

def create_payment(order_id: str, email: str, amount_units: int,
                   provider: str = "razorpay", status: str = "pending") -> Dict:
    item = {
        "PK": "ORDER#" + order_id, "SK": "META",
        "order_id": order_id, "email": email, "amount_units": amount_units,
        "provider": provider, "status": status, "created_at": _now(),
    }
    table().put_item(Item=item)
    return item


def complete_payment(order_id: str) -> Optional[Dict]:
    """Mark completed exactly once; returns the payment when this call won,
    None when it was already completed or unknown (idempotent webhooks)."""
    try:
        resp = table().update_item(
            Key={"PK": "ORDER#" + order_id, "SK": "META"},
            UpdateExpression="SET #s = :done",
            ConditionExpression="attribute_exists(PK) AND #s <> :done",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":done": "completed"},
            ReturnValues="ALL_NEW",
        )
        return _plain(resp["Attributes"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def init_db() -> None:
    """Touch the table so misconfiguration fails at startup, not first request."""
    table()
