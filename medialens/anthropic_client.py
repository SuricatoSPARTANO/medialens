import requests


def call_anthropic(prompt, api_key):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 3000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        },
        timeout=120
    )

    response.raise_for_status()
    data = response.json()

    return "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()
