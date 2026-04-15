from fastapi import APIRouter
from .auth import router as auth_router
from .ticket import router as artwork_router
from .blockchain import router as blockchain_router
from .web3 import router as web3_router
from .psl import router as psl_router  # PSL Entry X (Hackathon)
router = APIRouter()

# Include all versioned routers
router.include_router(auth_router)
router.include_router(artwork_router)
router.include_router(web3_router)
router.include_router(blockchain_router)
router.include_router(psl_router)  # PSL Entry X (Hackathon)
