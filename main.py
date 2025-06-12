import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

# ─── Corrected Imports ────────────────────────────────────────────────
from xrpl.models.transactions import Payment, MultiSignedTransaction
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo
from xrpl.transaction import (
    safe_sign_and_autofill_transaction,
    sign,
    send_reliable_submission,
)

# ─── CONFIGURATION ────────────────────────────────────────────────────
RPC_URL = os.getenv(
    "XRPL_RPC_URL",
    "https://s.altnet.rippletest.net:51234"
)
client = JsonRpcClient(RPC_URL)

ISSUER_SEED   = os.getenv("ISSUER_SEED")
SIGNER1_SEED  = os.getenv("SIGNER1_SEED")
SIGNER2_SEED  = os.getenv("SIGNER2_SEED")

issuer_wallet  = Wallet(seed=ISSUER_SEED)
signer1_wallet = Wallet(seed=SIGNER1_SEED)
signer2_wallet = Wallet(seed=SIGNER2_SEED)

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
        # 1) Build the base Payment transaction (single-sign template)
        payment_tx = Payment(
            account=issuer_wallet.classic_address,
            destination=issuer_wallet.classic_address,    # adjust if you want a different recipient
            amount=IssuedCurrencyAmount(
                currency=CURRENCY_HEX,
                issuer=issuer_wallet.classic_address,
                value=str(req.amount),
            ),
        )

        # 2) Autofill fee & sequence
        filled_tx = safe_sign_and_autofill_transaction(
            payment_tx, issuer_wallet, client
        )

        # 3) Apply 2-of-4 multisignature
        sig1 = sign(filled_tx, signer1_wallet, multisign=True)
        sig2 = sign(filled_tx, signer2_wallet, multisign=True)

        combined = sig1.tx_json["Signers"] + sig2.tx_json["Signers"]
        multisigned = MultiSignedTransaction.from_dict({
            **filled_tx.to_dict(),
            "Signers": combined
        })

        # 4) Submit and wait for validation
        resp = send_reliable_submission(multisigned, client)
        result = resp.result
        if result.get("engine_result") != "tesSUCCESS":
            raise HTTPException(
                status_code=500,
                detail=f"XRPL error: {result.get('engine_result')}"
            )

        return MintResponse(
            status="success",
            tx_hash=result["tx_json"]["hash"]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mint failed: {e}")
