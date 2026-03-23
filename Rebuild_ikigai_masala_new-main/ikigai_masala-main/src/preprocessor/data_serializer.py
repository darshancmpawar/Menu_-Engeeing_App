"""
Data serializer for storing and loading processed menu data - MVP Version
"""

import logging
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path
from typing import Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class DataSerializer:
    """
    Serializes cleaned menu data for efficient storage and retrieval.
    Stores data as numpy arrays along with metadata for fast loading.
    """
    
    def __init__(self, output_dir: str = "data/processed"):
        """
        Initialize the data serializer.
        
        Args:
            output_dir: Directory to store processed data
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def serialize(self, df: pd.DataFrame, dataset_name: str = "menu_data") -> Dict[str, str]:
        """
        Serialize the DataFrame for caching (MVP: pickle only).
        
        Args:
            df: Cleaned DataFrame to serialize
            dataset_name: Name for the dataset files
            
        Returns:
            Dictionary with paths to saved files
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{dataset_name}_{timestamp}"
        
        # Create simple metadata
        metadata = {
            'timestamp': timestamp,
            'row_count': len(df),
            'columns': list(df.columns)
        }
        
        # Save metadata
        metadata_path = self.output_dir / f"{base_name}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Save DataFrame as pickle
        pickle_path = self.output_dir / f"{base_name}.pkl"
        df.to_pickle(pickle_path)
        
        # Create a "latest" reference file
        latest_ref_path = self.output_dir / f"{dataset_name}_latest.json"
        with open(latest_ref_path, 'w') as f:
            json.dump({
                'latest_pickle': str(pickle_path.name),
                'latest_metadata': str(metadata_path.name),
                'timestamp': timestamp
            }, f, indent=2)
        
        logger.info("Saved to: %s", pickle_path.name)
        
        return {
            'pickle_path': str(pickle_path),
            'metadata_path': str(metadata_path)
        }
    
    def load_latest(self, dataset_name: str = "menu_data") -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Load the latest serialized dataset.
        
        Args:
            dataset_name: Name of the dataset to load
            
        Returns:
            Tuple of (DataFrame, metadata)
        """
        latest_ref_path = self.output_dir / f"{dataset_name}_latest.json"
        
        if not latest_ref_path.exists():
            raise FileNotFoundError(f"No serialized data found for '{dataset_name}'")
        
        with open(latest_ref_path, 'r') as f:
            latest_ref = json.load(f)
        
        # Load the pickle file
        pickle_path = self.output_dir / latest_ref['latest_pickle']
        df = pd.read_pickle(pickle_path)
        
        # Load metadata
        metadata_path = self.output_dir / latest_ref['latest_metadata']
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        logger.info("Loaded dataset: %d items from %s", len(df), pickle_path)
        return df, metadata
    
