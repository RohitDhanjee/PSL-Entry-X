from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user  # Use the consistent method
from app.db.database import get_user_collection, get_wallet_collection
from app.db.schemas import WalletSchema
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user
from app.db.database import get_user_collection, get_wallet_collection
from app.db.schemas import WalletSchema
from web3 import Web3
import secrets
from datetime import datetime

router = APIRouter(prefix="/blockchain", tags=["blockchain"])

@router.get("/wallet", response_model=WalletSchema)
async def get_wallet(current_user: dict = Depends(get_current_user)): # Changed to use get_current_user
    user_collection = get_user_collection()
    user = await user_collection.find_one({"email": current_user["sub"]})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    wallet_collection = get_wallet_collection()
    wallet = await wallet_collection.find_one({"user_id": current_user["user_id"]})
    
    if not wallet:
        private_key = "0x" + secrets.token_hex(32)
        w3 = Web3()
        acct = w3.eth.account.from_key(private_key)
        
        wallet_data = {
            "address": acct.address,
            "private_key": private_key,
            "balance": 0.0,
            "user_id": current_user["user_id"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await wallet_collection.insert_one(wallet_data)
        wallet = await wallet_collection.find_one({"_id": result.inserted_id})
        
        await user_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"wallet_address": acct.address}}
        )
    
    return WalletSchema(**wallet)

@router.get("/royalties")
async def get_royalties(current_user: dict = Depends(get_current_user)):  # Changed to use get_current_user
    return {
        "total_royalties": 0.0,
        "royalty_history": []
    }