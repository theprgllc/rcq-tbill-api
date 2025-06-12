import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.transactions import (
    Payment,
    IssuedCurrencyAmount,
    MultiSignedTransaction,
)
from xrpl.models.transactions import SignerEntry
from xrpl.models.requests import AccountInfo
from xrpl.transaction import safe_sign_and_autofill_transaction, sign, send_reliable_submission


from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="RCQ-TBILL Multisig Issuance")

# 1) XRPL Client (Testnet/Mainnet switch)
RPC_URL = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234")
client  = JsonRpcClient(RPC_URL)

# 2) Load seeds from Env
issuer_seed   = os.getenv("ISSUER_SEED")
signer1_seed  = os.getenv("SIGNER1_SEED")
signer2_seed  = os.getenv("SIGNER2_SEED")

# 3) Instantiate Wallets
issuer_wallet  = Wallet(seed=issuer_seed)
signer1_wallet = Wallet(seed=signer1_seed)
signer2_wallet = Wallet(seed=signer2_seed)

# 4) Token Definition (40-char HEX for RCQ-TBILL)
CURRENCY_HEX = "5243512D5442494C4C0000000000000000000000"

class MintRequest(BaseModel):
    cusip: str
    amount: float
    date: str       # ISO 8601 date string
    # Optional: destination: str

class MintResponse(BaseModel):
    status: str
    tx_hash: str
app = FastAPI(title="RCQ-TBILL Token Issuance API")

@app.post("/mint", response_model=MintResponse)
def mint_tbill(req: MintRequest):
    try:
        # ── Build the base Payment ─────────────────────────
        payment_tx = Payment(
            account=issuer_wallet.classic_address,
            destination=req.destination if hasattr(req, "destination") else issuer_wallet.classic_address,
            amount=IssuedCurrencyAmount(
                currency=CURRENCY_HEX,
                issuer=issuer_wallet.classic_address,
                value=str(req.amount),
            ),
        )
        # ── Autofill fee & sequence ─────────────────────────
        filled_tx = safe_sign_and_autofill_transaction(payment_tx, issuer_wallet, client)

        # ── Collect multisigs ───────────────────────────────
        sig1 = sign(filled_tx, signer1_wallet, multisign=True)
        sig2 = sign(filled_tx, signer2_wallet, multisign=True)

        combined = sig1.tx_json["Signers"] + sig2.tx_json["Signers"]
        multi_signed = MultiSignedTransaction.from_dict({
            **filled_tx.to_dict(),
            "Signers": combined
        })

        # ── Submit & confirm ────────────────────────────────
        resp = send_reliable_submission(multi_signed, client)
        result = resp.result
        if result["engine_result"] != "tesSUCCESS":
            raise HTTPException(500, f"XRPL error: {result['engine_result']}")

        return MintResponse(status="success", tx_hash=result["tx_json"]["hash"])

    except Exception as e:
        raise HTTPException(500, f"Mint failed: {str(e)}")

@app.get("/")
async def root():
    return {"message": "RCQ-TBILL API is live. Use /docs for API."}

# === Config ===
XRPL_ISSUER_ADDRESS = "rXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # Your Trust's XRPL address

# === Models ===
class TBillActionRequest(BaseModel):
    cusip: str
    amount: float
    date: str  # ISO format (e.g., 2025-06-10)

class TBillActionResponse(BaseModel):
    status: str
    tx_hash: Optional[str]
    message: Optional[str] = None

# === Mint Endpoint ===
@app.post("/mint", response_model=TBillActionResponse)
async def mint_token(req: TBillActionRequest):
    try:
        tx_hash = f"SIMULATED_TX_HASH_MINT_{req.cusip}"
        return TBillActionResponse(status="success", tx_hash=tx_hash)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Burn Endpoint ===
@app.post("/burn", response_model=TBillActionResponse)
async def burn_token(req: TBillActionRequest):
    try:
        tx_hash = f"SIMULATED_TX_HASH_BURN_{req.cusip}"
        return TBillActionResponse(status="success", tx_hash=tx_hash)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Audit Log Placeholder ===
@app.get("/audit-log")
async def audit_log():
    return {"status": "pending", "logs": []}
