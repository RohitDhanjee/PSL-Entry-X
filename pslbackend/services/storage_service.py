"""
Unified Storage Service handling MongoDB GridFS and Similarity Search.
Includes ResNet-50 embedding computation for similarity matching.
"""
import logging
import hashlib
import io
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import numpy as np
import imagehash
from PIL import Image

import torch
import torchvision.models as models
import torchvision.transforms as transforms

from motor.motor_asyncio import AsyncIOMotorGridFSBucket, AsyncIOMotorDatabase
from bson import ObjectId

logger = logging.getLogger(__name__)


# ==========================
# Settings
# ==========================

class SimilaritySettings:
    """Similarity search settings from environment."""
    
    def __init__(self):
        self.TOP_K = int(os.getenv("SIMILARITY_TOP_K", "10"))
        self.PHASH_THRESHOLD = int(os.getenv("PHASH_THRESHOLD", "10"))
        self.EMBEDDING_THRESHOLD = float(os.getenv("EMBEDDING_THRESHOLD", "0.85"))
        self.EMBEDDING_DIM = 2048


similarity_settings = SimilaritySettings()


# ==========================
# ResNet-50 Embedding Service
# ==========================

class EmbeddingService:
    """
    Computes image embeddings using ResNet-50.
    Produces 2048-dimensional feature vectors.
    """
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern to avoid loading model multiple times."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        logger.info("Loading ResNet-50 model...")
        
        # Load pretrained ResNet-50
        self.model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
        
        # Remove final classification layer to get embeddings
        self.model = torch.nn.Sequential(*list(self.model.children())[:-1])
        self.model.eval()
        
        # Use GPU if available
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self.model.to(self.device)
        
        # Image preprocessing
        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            ),
        ])
        
        self._initialized = True
        logger.info(f"ResNet-50 loaded on {self.device}")
    
    def compute_embedding(self, image_bytes: bytes) -> Optional[np.ndarray]:
        """
        Compute ResNet-50 embedding for an image.
        Returns 2048-dimensional numpy array or None if failed.
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            img_tensor = self.transform(img).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                embedding = self.model(img_tensor)
            
            embedding = embedding.squeeze().cpu().numpy()
            embedding = embedding / np.linalg.norm(embedding)
            
            return embedding.astype(np.float32)
            
        except Exception as e:
            logger.error(f"Embedding computation failed: {e}")
            return None


# ==========================
# Hash Service
# ==========================

class HashService:
    """Computes perceptual hashes for images."""
    
    @staticmethod
    def compute_phash(image_bytes: bytes) -> Optional[str]:
        """Compute perceptual hash for an image."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            return str(imagehash.phash(img))
        except Exception as e:
            logger.error(f"pHash computation failed: {e}")
            return None
    
    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        """Compute Hamming distance between two hashes."""
        try:
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            return int(h1 - h2)  # Convert to Python int
        except Exception:
            return 64  # Maximum distance


# ==========================
# Storage Service
# ==========================

class StorageService:
    """
    Handles all storage operations:
    1. Image storage in GridFS
    2. Metadata storage for search
    3. Similarity search against existing database
    """
    
    def __init__(self, db: AsyncIOMotorDatabase, metadata_db: AsyncIOMotorDatabase):
        self.db = db
        self.metadata_db = metadata_db
        
        # GridFS bucket for downloaded images
        self.bucket = AsyncIOMotorGridFSBucket(db)
        
        # Collection for existing artwork metadata
        self.existing_images_col = metadata_db.artworks
        
        # Initialize services
        self.embedding_service = EmbeddingService()
        self.hash_service = HashService()
    
    # =========================
    # GridFS Operations
    # =========================
    
    async def store_image(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        metadata: Optional[Dict[str, Any]] = None
    ) -> ObjectId:
        """Store image in GridFS with deduplication."""
        if metadata is None:
            metadata = {}
        
        file_hash = f"sha256:{hashlib.sha256(file_data).hexdigest()}"
        metadata["file_hash"] = file_hash
        metadata["uploaded_at"] = datetime.now(timezone.utc)
        metadata["content_type"] = content_type
        
        # Check for existing file by hash
        existing = await self.db.fs.files.find_one({"metadata.file_hash": file_hash})
        if existing:
            logger.info(f"Image already exists: {existing['_id']}")
            return existing["_id"]
        
        # Upload to GridFS
        grid_in = self.bucket.open_upload_stream(filename, metadata=metadata)
        await grid_in.write(file_data)
        await grid_in.close()
        
        logger.info(f"Stored image {filename}: {grid_in._id}")
        return grid_in._id
    
    async def get_image(self, gridfs_id: ObjectId) -> Optional[bytes]:
        """Retrieve image bytes from GridFS."""
        try:
            if isinstance(gridfs_id, str):
                gridfs_id = ObjectId(gridfs_id)
            grid_out = await self.bucket.open_download_stream(gridfs_id)
            return await grid_out.read()
        except Exception as e:
            logger.error(f"Error reading GridFS file {gridfs_id}: {e}")
            return None
    
    async def delete_image(self, gridfs_id: ObjectId) -> bool:
        """Delete image from GridFS."""
        try:
            if isinstance(gridfs_id, str):
                gridfs_id = ObjectId(gridfs_id)
            await self.bucket.delete(gridfs_id)
            return True
        except Exception as e:
            logger.error(f"Error deleting GridFS file {gridfs_id}: {e}")
            return False
    
    # =========================
    # Embedding & Hash Computation
    # =========================
    
    def compute_image_features(self, image_bytes: bytes) -> Dict[str, Any]:
        """Compute both embedding and perceptual hash for an image."""
        return {
            "embedding": self.embedding_service.compute_embedding(image_bytes),
            "perceptual_hash": self.hash_service.compute_phash(image_bytes)
        }
    
    # =========================
    # Similarity Search
    # =========================
    
    async def search_similar(
        self,
        query_embedding: Optional[np.ndarray] = None,
        query_phash: Optional[str] = None,
        hash_threshold: int = 10,
        embedding_threshold: float = 0.85,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for similar images in existing database."""
        results = []
        
        # Query the existing images collection
        cursor = self.existing_images_col.find({
            "$or": [
                {"image_metadata.embedding": {"$exists": True}},
                {"image_metadata.perceptual_hash": {"$exists": True}},
                {"image_metadata.perpetual_hash": {"$exists": True}}
            ]
        })
        
        async for doc in cursor:
            meta = doc.get("image_metadata", {})
            score = 0.0
            match_details = {}
            
            db_hash = meta.get("perceptual_hash") or meta.get("perpetual_hash")
            db_embedding = meta.get("embedding")
            
            # Hash comparison
            if query_phash and db_hash:
                distance = self.hash_service.hamming_distance(query_phash, db_hash)
                if distance <= hash_threshold:
                    hash_score = 1 - (distance / 64)
                    score += hash_score * 0.4
                    match_details["hash_distance"] = int(distance)  # Ensure Python int
                    match_details["hash_similarity"] = float(hash_score)  # Ensure Python float
            
            # Embedding comparison
            if query_embedding is not None and db_embedding:
                try:
                    db_emb_array = np.array(db_embedding, dtype=np.float32)
                    similarity = self._cosine_similarity(query_embedding, db_emb_array)
                    if similarity >= embedding_threshold:
                        score += similarity * 0.6
                        match_details["embedding_similarity"] = float(min(similarity, 1.0))
                except Exception as e:
                    logger.warning(f"Embedding comparison failed: {e}")
            
            if score > 0:
                match_type = "both"
                if "hash_distance" in match_details and "embedding_similarity" not in match_details:
                    match_type = "hash"
                elif "embedding_similarity" in match_details and "hash_distance" not in match_details:
                    match_type = "embedding"
                
                results.append({
                    "db_id": str(doc["_id"]),
                    "db_image_name": doc.get("title", doc.get("filename", meta.get("filename", "unknown"))),
                    "artist_name": doc.get("name"),
                    "artist_email": doc.get("email"),
                    "score": float(round(score, 4)),
                    "match_type": match_type,
                    "details": match_details
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        result = np.dot(v1, v2) / (norm1 * norm2)
        return float(result)  # Ensure Python float
