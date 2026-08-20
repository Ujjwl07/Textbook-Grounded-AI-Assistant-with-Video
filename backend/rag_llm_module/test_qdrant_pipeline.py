import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient

from prompt_manager import PromptManager
from script_generator import ScriptGenerator, MockLLMClient

# Load environment variables
load_dotenv(".env")

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "textbook_chunks")

async def test_real_qdrant():
    print(f"Connecting to Qdrant at {QDRANT_URL}...")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    
    # Check collection
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]
    print(f"Available collections: {collection_names}")
    
    if QDRANT_COLLECTION not in collection_names:
        print(f"Error: Collection {QDRANT_COLLECTION} not found in Qdrant!")
        return
        
    print("\nFetching real textbook chunks from Qdrant via scroll()...")
    
    # Fetch 3 real chunks from the database
    results, next_page = client.scroll(
        collection_name=QDRANT_COLLECTION,
        limit=3,
        with_payload=True
    )
    
    print(f"\nRetrieved {len(results)} chunks from Qdrant:")
    
    context_chunks = []
    subject = "Physics"
    chapter_name = "Laws of Motion"
    class_num = 11
    
    for i, res in enumerate(results, 1):
        payload = res.payload
        content = payload.get("content", "")
        print(f"\n--- Chunk {i} ---")
        print(f"Source: Class {payload.get('class_level')} {payload.get('subject')} - Ch {payload.get('chapter_number')} ({payload.get('chapter_name')})")
        print(f"Preview: {content[:150]}...")
        context_chunks.append(content)
        
        # Take metadata from the best match
        if i == 1:
            subject = payload.get("subject", "Physics")
            chapter_name = payload.get("chapter_name", "Laws of Motion")
            class_num = int(payload.get("class_level", 11) or 11)
            
    retrieved_context = "\n\n".join(context_chunks)
    
    print("\n" + "="*50)
    print("Testing Pipeline with Retrieved Context (Mock LLM)")
    print("="*50)
    
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client = MockLLMClient()
    generator = ScriptGenerator(prompt_manager=prompt_manager, llm_client=llm_client)
    
    # Mock a topic name based on the chapter
    topic = f"{chapter_name} Concepts"
    
    script = await generator.generate_script(
        subject=subject,
        topic=topic,
        chapter=chapter_name,
        class_num=class_num,
        retrieved_context=retrieved_context,
        prompt_version="v3"
    )
    
    print("\nPipeline Result:")
    print(f"Subject: {subject}")
    print(f"Topic: {topic}")
    print(f"Sections generated: {len(script.sections)}")
    print(f"Total words: {script.total_word_count}")
    print(f"Is valid: {script.validation.is_valid}")
    print(f"Context grounded: {script.validation.context_grounded}")
    
    print("\nFirst section preview (HOOK):")
    if script.sections:
        print(script.sections[0].content[:200] + "...")

if __name__ == "__main__":
    asyncio.run(test_real_qdrant())
