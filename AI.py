import json
import os
from groq import Groq

client = Groq(
    api_key="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",
)


def get_quote_from_response(email_content):
    prompt = ("Read the below email I have requested a quote for my cargo transport.try to find the response value. "
              "Response must json format with elements amount value and currency type."
              "If not able to determine, use the same format and in value mention  - Unable to determine. "
              "Dont give me any other text other than json content. The email starts below. ")
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt + "\n" + email_content
            }
        ],
        model="llama3-8b-8192",
    )
    response = json.loads(chat_completion.choices[0].message.content)
    quote = response.get('amount')
    return quote
