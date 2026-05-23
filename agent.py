import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()  # reads ANTHROPIC_API_KEY from environment

def handle_message(guest_message):
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",   # cheap/fast model for now
        max_tokens=300,
        system="You are a vacation rental assistant. Classify the guest's message (pre-booking, check-in, mid-stay, complaint, or review) and draft a short, friendly reply.",
        messages=[{"role": "user", "content": guest_message}],
    )
    return response.content[0].text

if __name__ == "__main__":
    test = "Hi! What time is check-in, and is there parking?"
    print(handle_message(test))
