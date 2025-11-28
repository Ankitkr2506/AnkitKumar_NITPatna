from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from extractor import extract_bill_info_from_url

app = FastAPI()

class BillRequest(BaseModel):
    document: str  # URL pointing to the bill image

@app.post("/extract-bill-data")
async def extract_bill_data(payload: BillRequest):
    """
    Accepts an image URL and returns parsed bill information.
    """
    try:
        result = extract_bill_info_from_url(payload.document)
        return {
            "is_success": True,
            "data": result,
            "error": None
        }
    except Exception as err:
        # Raise an HTTPException or respond gracefully
        return {
            "is_success": False,
            "data": None,
            "error": f"Processing failed: {err}"
        }
