import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.transactions import Payment
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo, Submit
from xrpl.transaction import safe_sign_and_autofill_transaction, sign

# ─── CONFIGURATION ────────────────────────────────────────────────────
RPC_URL = os.getenv(
    "XRPL_RPC_URL",
    "https://s.altnet.rippletest.net:51234"
)
client = JsonRpcClient(RPC_URL)

# Load and validate environment seeds
ISSUER_SEED = os.getenv("ISSUER_SEED")
SIGNER1_SEED = os.getenv("SIGNER1_SEED")
SIGNER2_SEED = os.getenv("SIGNER2_SEED")
for key, value in [("ISSUER_SEED", ISSUER_SEED), ("SIGNER1_SEED", SIGNER1_SEED), ("SIGNER2_SEED", SIGNER2_SEED)]:
    if not value:
        raise RuntimeError(f"Environment variable {key} is not set. Please configure it.")

# Use Wallet.from_seed to avoid constructor changes
issuer_wallet = Wallet.from_seed(ISSUER_SEED)
signer1_wallet = Wallet.from_seed(SIGNER1_SEED)
signer2_wallet = Wallet.from_seed(SIGNER2_SEED)

# RCQ-TBILL token code (40-character HEX)
CURRENCY_HEX = "5243512D5442494C4C0000000000000000000000"

# ─── Pydantic Models ───────────────────────────────────────────────────
class MintRequest(BaseModel):
    cusip: str
    amount: float
    date: str    # ISO 8601 date string

class MintResponse(BaseModel):
    status: str
    tx_hash: str

# ─── FastAPI App ──────────────────────────────────────────────────────
app = FastAPI(title="RCQ-TBILL Multisig Issuance API")

@app.get("/")
async def root():
    return {"message": "RCQ-TBILL API is live. Use /docs for API."}

@app.post("/mint", response_model=MintResponse)
def mint_tbill(req: MintRequest):
    try:
        # 1) Build base Payment
        payment_tx = Payment(
            account=issuer_wallet.classic_address,
            destination=issuer_wallet.classic_address,
            amount=IssuedCurrencyAmount(
                currency=CURRENCY_HEX,
                issuer=issuer_wallet.classic_address,
                value=str(req.amount),
            ),
        )

        # 2) Autofill
        filled_tx = safe_sign_and_autofill_transaction(
            payment_tx, issuer_wallet, client
        )

        # 3) Multisign
        sig1 = sign(filled_tx, signer1_wallet, multisign=True)
        sig2 = sign(filled_tx, signer2_wallet, multisign=True)
        combined = sig1.tx_json["Signers"] + sig2.tx_json["Signers"]

        # 4) Submit
        multi_signed_payload = {**filled_tx.to_dict(), "Signers": combined}
        submit_req = Submit(tx_json=multi_signed_payload)
        submit_resp = client.request(submit_req).result

        if submit_resp.get("engine_result") != "tesSUCCESS":
            raise HTTPException(
                status_code=500,
                detail=f"XRPL error: {submit_resp.get('engine_result')}"
            )

        return MintResponse(
            status="success",
            tx_hash=submit_resp["tx_json"]["hash"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mint failed: {e}")

