"""
Multi-level caching for SQL results, dataset selections, and responses
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.database.models import CacheEntry
from app.database.connection import SessionLocal


class CacheService:
    """Multi-level caching for SQL results, dataset selections, and responses"""
    
    def __init__(self):
        self.ttl_config = {
            "sql_result": timedelta(hours=1),       # SQL results expire quickly
            "column_search": timedelta(hours=6),    # Column search context is moderately stable
            "sql_generation": timedelta(hours=6),   # SQL generation cached medium-term
            "metadata": timedelta(hours=12)         # Metadata changes occasionally
        }
    
    def generate_cache_key(self, cache_type: str, **kwargs) -> str:
        """
        Generate deterministic cache key from parameters
        
        Args:
            cache_type: Type of cache entry
            **kwargs: Parameters to include in cache key
        
        Returns:
            32-character hash string
        """
        # Sort keys for consistent hashing
        sorted_params = json.dumps(kwargs, sort_keys=True, default=str)
        hash_input = f"{cache_type}:{sorted_params}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]
    
    def get(self, cache_type: str, **kwargs) -> Optional[Any]:
        """
        Get cached value if exists and not expired
        
        Args:
            cache_type: Type of cache entry
            **kwargs: Parameters that define this cache entry
        
        Returns:
            Cached value or None
        """
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        
        db = SessionLocal()
        try:
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key,
                CacheEntry.cache_type == cache_type
            ).first()
            
            if not entry:
                return None
            
            # Check expiration
            if entry.expires_at and entry.expires_at < datetime.now():
                db.delete(entry)
                db.commit()
                return None
            
            # Update hit count and last accessed
            entry.hit_count += 1
            entry.last_accessed = datetime.now()
            db.commit()
            
            return entry.value
            
        except Exception as e:
            print(f"Cache get error: {str(e)}")
            return None
        finally:
            db.close()
    
    def set(self, cache_type: str, value: Any, **kwargs):
        """
        Store value in cache
        
        Args:
            cache_type: Type of cache entry
            value: Value to cache (must be JSON-serializable)
            **kwargs: Parameters that define this cache entry
        """
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        ttl = self.ttl_config.get(cache_type)
        expires_at = datetime.now() + ttl if ttl else None
        
        db = SessionLocal()
        try:
            # Upsert
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key
            ).first()
            
            if entry:
                entry.value = value
                entry.expires_at = expires_at
                entry.last_accessed = datetime.now()
            else:
                entry = CacheEntry(
                    cache_key=cache_key,
                    cache_type=cache_type,
                    value=value,
                    created_at=datetime.now(),
                    expires_at=expires_at,
                    last_accessed=datetime.now()
                )
                db.add(entry)
            
            db.commit()
            
        except Exception as e:
            db.rollback()
            print(f"Cache set error: {str(e)}")
        finally:
            db.close()
    
    def invalidate(self, cache_type: str, **kwargs):
        """Invalidate specific cache entry"""
        cache_key = self.generate_cache_key(cache_type, **kwargs)
        
        db = SessionLocal()
        try:
            entry = db.query(CacheEntry).filter(
                CacheEntry.cache_key == cache_key
            ).first()
            
            if entry:
                db.delete(entry)
                db.commit()
                
        except Exception as e:
            db.rollback()
            print(f"Cache invalidate error: {str(e)}")
        finally:
            db.close()
    
    def clear_expired(self):
        """Remove all expired cache entries"""
        db = SessionLocal()
        try:
            deleted = db.query(CacheEntry).filter(
                CacheEntry.expires_at < datetime.now()
            ).delete()
            
            db.commit()
            return deleted
            
        except Exception as e:
            db.rollback()
            print(f"Cache clear error: {str(e)}")
            return 0
        finally:
            db.close()
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        db = SessionLocal()
        try:
            total_entries = db.query(CacheEntry).count()
            
            # Calculate hit rate (if entries have been accessed)
            entries = db.query(CacheEntry).all()
            total_hits = sum(e.hit_count for e in entries)
            
            # Group by cache type
            type_counts = {}
            for entry in entries:
                type_counts[entry.cache_type] = type_counts.get(entry.cache_type, 0) + 1
            
            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "avg_hit_rate": total_hits / total_entries if total_entries > 0 else 0,
                "by_type": type_counts
            }
            
        finally:
            db.close()


