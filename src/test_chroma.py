import chromadb

print("1. creating client", flush=True)
client = chromadb.PersistentClient(path="./chroma_test")
print("2. getting collection", flush=True)
col = client.get_or_create_collection("test_col", metadata={"hnsw:space": "cosine"})
print("3. upsert", flush=True)
col.upsert(ids=["a"], documents=["hello"], embeddings=[[0.1] * 384], metadatas=[{"k": 1}])
print("4. get", flush=True)
print(col.get(where={"k": 1}, include=[]), flush=True)
print("5. delete", flush=True)
col.delete(ids=["a"])
print("done", flush=True)