from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime



# class UserSchema(BaseModel):
#     email: str
#     username: str
#     full_name: Optional[str] = None
#     role: str
#     is_active: bool
#     wallet_address: Optional[str] = None
#     created_at: datetime
#     updated_at: datetime

#     model_config = ConfigDict(from_attributes=True)

class ArtworkSchema(BaseModel):
    title: str
    description: Optional[str] = None
    ipfs_hash: str
    blockchain_tx: str
    price: float
    is_for_sale: bool = True
    royalty_percentage: float
    artist_id: str
    is_verified: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class WalletSchema(BaseModel):
    address: str
    balance: float
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InfoRequestBody(BaseModel):
    message: str
    requested_by: Optional[str] = None  # Example optional field
