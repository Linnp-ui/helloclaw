import asyncio
import httpx
import base64
import json

async def test_multimodal():
    url = "http://localhost:8000/api/chat/send/stream"
    
    # A tiny 1x1 black pixel PNG image in base64
    pixel_png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    data_url = f"data:image/png;base64,{pixel_png_base64}"
    
    payload = {
        "message": "这是一张纯黑色的1x1像素点图片，请你简单描述一下收到了这张图片。",
        "images": [data_url]
    }
    
    print(f"Sending request to {url}...")
    headers = {
        "Accept": "text/event-stream"
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    print(f"Error: {response.status_code}")
                    content = await response.aread()
                    print(content.decode())
                    return
                print("Connected! Reading stream...\n")
                async for chunk in response.aiter_text():
                    print(chunk, end="", flush=True)
                print("\n\nStream Finished.")
    except Exception as e:
        print(f"Connection failed: {e}. Is the backend server running?")

if __name__ == "__main__":
    asyncio.run(test_multimodal())
