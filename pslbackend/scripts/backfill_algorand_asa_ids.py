import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.database import connect_to_mongo, close_mongo_connection, get_artwork_collection
from services.algorand_service import AlgorandService


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_algorand_asa_ids")


def _parse_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _extract_created_asset_index_from_indexer(indexer_response: dict) -> Optional[int]:
    txns = indexer_response.get("transactions", []) if isinstance(indexer_response, dict) else []
    if not txns:
        return None

    created_index = txns[0].get("created-asset-index")
    return _parse_positive_int(created_index)


async def _resolve_asa_id_for_doc(algorand_service: AlgorandService, doc: dict) -> tuple[Optional[int], str]:
    tx_hash = (doc.get("tx_hash") or "").strip()
    token_id = _parse_positive_int(doc.get("token_id"))

    # 1) Primary: derive from registration tx hash
    if tx_hash:
        try:
            pending = algorand_service.algod_client.pending_transaction_info(tx_hash)
            asa_id = _parse_positive_int(pending.get("asset-index"))
            if asa_id:
                return asa_id, "algod_pending_tx"
        except Exception as pending_error:
            logger.debug("Pending tx lookup failed for %s: %s", tx_hash, pending_error)

        try:
            idx_resp = algorand_service.indexer_client.search_transactions(txid=tx_hash, limit=1)
            asa_id = _extract_created_asset_index_from_indexer(idx_resp)
            if asa_id:
                return asa_id, "indexer_tx"
        except Exception as indexer_error:
            logger.debug("Indexer tx lookup failed for %s: %s", tx_hash, indexer_error)

    # 2) Secondary: validate token_id as ASA
    if token_id:
        try:
            chain_info = await algorand_service.get_asset_blockchain_info(token_id)
            if chain_info.get("success"):
                return token_id, "validated_token_id"
        except Exception as token_validate_error:
            logger.debug("Token validation failed for %s: %s", token_id, token_validate_error)

    return None, "unresolved"


async def main(apply_changes: bool) -> int:
    await connect_to_mongo()
    try:
        artworks = get_artwork_collection()
        algorand_service = AlgorandService()

        query = {
            "network": "algorand",
            "$or": [
                {"algorand_asa_id": {"$exists": False}},
                {"algorand_asa_id": None},
                {"algorand_asa_id": 0},
            ],
        }

        docs = await artworks.find(query).to_list(length=5000)
        logger.info("Found %d Algorand artwork(s) with missing algorand_asa_id", len(docs))

        updated = 0
        unresolved = 0

        for doc in docs:
            asa_id, source = await _resolve_asa_id_for_doc(algorand_service, doc)
            artwork_id = str(doc.get("_id"))
            tx_hash = doc.get("tx_hash")
            token_id = doc.get("token_id")

            if not asa_id:
                unresolved += 1
                logger.warning(
                    "UNRESOLVED artwork_id=%s token_id=%s tx_hash=%s",
                    artwork_id,
                    token_id,
                    tx_hash,
                )
                continue

            logger.info(
                "%s artwork_id=%s token_id=%s -> asa_id=%s via %s",
                "APPLY" if apply_changes else "DRYRUN",
                artwork_id,
                token_id,
                asa_id,
                source,
            )

            if apply_changes:
                await artworks.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"algorand_asa_id": asa_id}},
                )
                updated += 1

        logger.info(
            "Backfill complete. apply=%s updated=%d unresolved=%d total=%d",
            apply_changes,
            updated,
            unresolved,
            len(docs),
        )
        return 0
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing algorand_asa_id values for Algorand artworks")
    parser.add_argument("--apply", action="store_true", help="Apply DB updates. Default is dry-run.")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(main(apply_changes=args.apply)))
