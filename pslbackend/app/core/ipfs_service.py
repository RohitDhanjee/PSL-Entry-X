import aiohttp
import base64
from app.core.config import settings

async def upload_to_ipfs(file):
    # This is a mock implementation
    # In a real app, you would use the IPFS API with your API key
    file_content = await file.read()
    return f"ipfs_hash_{base64.b64encode(file_content[:10]).decode()}"