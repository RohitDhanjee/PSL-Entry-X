import asyncio
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from algosdk import mnemonic, account
from algosdk.logic import get_application_address
from algosdk.v2client import algod
from algosdk import transaction


APPROVAL_PROGRAM = """#pragma version 8
// Accept app creation and all future NoOp calls.
int 1
"""

CLEAR_PROGRAM = """#pragma version 8
int 1
"""


def _load_env() -> None:
    root_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(root_env)


def _resolve_deployer_credentials() -> tuple[str, str]:
    deployer_mnemonic = (os.getenv("ALGORAND_DEPLOYER_MNEMONIC", "") or "").strip()
    deployer_private_key = (os.getenv("ALGORAND_DEPLOYER_PRIVATE_KEY", "") or "").strip()

    if deployer_mnemonic:
        words = [w for w in deployer_mnemonic.split(" ") if w.strip()]
        if len(words) == 25:
            sk = mnemonic.to_private_key(deployer_mnemonic)
            addr = account.address_from_private_key(sk)
            return sk, addr

        if len(words) == 24:
            raise RuntimeError(
                "ALGORAND_DEPLOYER_MNEMONIC has 24 words. Algorand mnemonic must be 25 words. "
                "Use a 25-word Algorand passphrase, or set ALGORAND_DEPLOYER_PRIVATE_KEY instead."
            )

        raise RuntimeError(
            f"ALGORAND_DEPLOYER_MNEMONIC has {len(words)} words; expected 25."
        )

    if deployer_private_key:
        try:
            addr = account.address_from_private_key(deployer_private_key)
            return deployer_private_key, addr
        except Exception as private_key_error:
            raise RuntimeError(
                "ALGORAND_DEPLOYER_PRIVATE_KEY is invalid. "
                "Expected Algorand private key format returned by algosdk.account.generate_account()."
            ) from private_key_error

    raise RuntimeError(
        "Missing deployer credentials. Set ALGORAND_DEPLOYER_MNEMONIC (25 words) "
        "or ALGORAND_DEPLOYER_PRIVATE_KEY in drmbackend/.env"
    )


async def main() -> None:
    _load_env()

    algod_url = os.getenv("ALGORAND_ALGOD_URL", "https://testnet-api.algonode.cloud")
    algod_token = os.getenv("ALGORAND_ALGOD_TOKEN", "")
    deployer_private_key, deployer_address = _resolve_deployer_credentials()

    client = algod.AlgodClient(algod_token, algod_url)

    status = client.status()
    print(f"Connected to algod. Last round: {status.get('last-round')}")
    print(f"Deployer: {deployer_address}")

    balance = client.account_info(deployer_address).get("amount", 0)
    print(f"Deployer balance: {balance / 1_000_000:.6f} ALGO")

    if balance < 300_000:
        raise RuntimeError("Insufficient balance. Fund deployer with at least 0.3 ALGO on testnet.")

    approval_compiled = client.compile(APPROVAL_PROGRAM)
    clear_compiled = client.compile(CLEAR_PROGRAM)

    approval_program = base64.b64decode(approval_compiled["result"])
    clear_program = base64.b64decode(clear_compiled["result"])

    params = client.suggested_params()

    txn = transaction.ApplicationCreateTxn(
        sender=deployer_address,
        sp=params,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=transaction.StateSchema(num_uints=0, num_byte_slices=0),
        local_schema=transaction.StateSchema(num_uints=0, num_byte_slices=0),
        app_args=[],
    )

    signed_txn = txn.sign(deployer_private_key)
    txid = client.send_transaction(signed_txn)
    print(f"App create submitted. TxID: {txid}")

    confirmation = transaction.wait_for_confirmation(client, txid, 8)

    app_id = confirmation.get("application-index")
    if not app_id:
        pending = client.pending_transaction_info(txid)
        app_id = pending.get("application-index")

    if not app_id:
        raise RuntimeError("Deployment confirmed but application-index not found.")

    app_address = get_application_address(int(app_id))

    print("\nDeployment complete")
    print(f"ALGORAND_APP_ID={app_id}")
    print(f"ALGORAND_APP_ADDRESS={app_address}")
    print("\nNext steps:")
    print("1) Put ALGORAND_APP_ID in drmbackend/.env")
    print("2) Restart backend server")
    print("3) Backfill artworks.algorand_app_id for old Algorand artworks")


if __name__ == "__main__":
    asyncio.run(main())
