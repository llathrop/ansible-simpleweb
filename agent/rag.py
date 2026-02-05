import os
import glob
import logging
import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

class RAGEngine:
    def __init__(self, persist_directory=None):
        if not persist_directory:
            persist_directory = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'chroma')
        
        logger.info(f"Initializing RAG Engine at {persist_directory}")
        
        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="ansible_knowledge",
            metadata={"hnsw:space": "cosine"}
        )

    def ingest_data(self, playbooks_dir, docs_dir):
        """Ingest playbooks and documentation into the vector store."""
        logger.info("Starting ingestion...")
        
        # Clear existing? For now, we might want to upsert.
        # Simple strategy: Read all files, add them.
        
        documents = []
        ids = []
        metadatas = []
        
        # 1. Ingest Playbooks
        if os.path.exists(playbooks_dir):
            playbook_files = glob.glob(os.path.join(playbooks_dir, '*.yml')) + \
                             glob.glob(os.path.join(playbooks_dir, '*.yaml'))
            
            for f in playbook_files:
                try:
                    with open(f, 'r') as file:
                        content = file.read()
                        filename = os.path.basename(f)
                        documents.append(content)
                        ids.append(f"playbook-{filename}")
                        metadatas.append({"source": filename, "type": "playbook"})
                except Exception as e:
                    logger.error(f"Failed to read playbook {f}: {e}")

        # 2. Ingest Docs
        if os.path.exists(docs_dir):
            doc_files = glob.glob(os.path.join(docs_dir, '*.md'))
            
            for f in doc_files:
                try:
                    with open(f, 'r') as file:
                        content = file.read()
                        filename = os.path.basename(f)
                        documents.append(content)
                        ids.append(f"doc-{filename}")
                        metadatas.append({"source": filename, "type": "documentation"})
                except Exception as e:
                    logger.error(f"Failed to read doc {f}: {e}")

        if documents:
            logger.info(f"Upserting {len(documents)} documents...")
            self.collection.upsert(
                documents=documents,
                ids=ids,
                metadatas=metadatas
            )
            logger.info("Ingestion complete.")
        else:
            logger.warning("No documents found to ingest.")

    def query(self, text, n_results=3):
        """Query the vector store for relevant context."""
        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=n_results
            )
            return results['documents'][0] if results['documents'] else []
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []
