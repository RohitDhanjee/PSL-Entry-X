import asyncio
from pydantic import BaseModel, Field
from typing import Any, Optional
from bson import ObjectId

# Mocking the PyObjectId implementation from models.py
class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler) -> Any:
        from pydantic_core import core_schema
        return core_schema.with_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def validate(cls, v: Any, info) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str):
            if ObjectId.is_valid(v):
                return v
            raise ValueError("Invalid ObjectId string")
        raise ValueError("Invalid ObjectId type")

class LicenseConfig(BaseModel):
    id: Optional[PyObjectId] = Field(None, alias="_id")
    name: str

def test_config():
    # Simulate DB doc with ObjectId
    doc = {
        "_id": ObjectId('69c04a64129341920faac411'),
        "name": "Test Config"
    }
    
    try:
        config = LicenseConfig(**doc)
        print("✅ Validation Success!")
        print(f"ID: {config.id}")
        print(f"Model Dump: {config.model_dump(by_alias=True)}")
    except Exception as e:
        print(f"❌ Validation Failed: {e}")

if __name__ == "__main__":
    test_config()
