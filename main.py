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
from xrpl.models.requests import AccountInfo
from xrpl.transaction import (
    safe_sign_and_autofill_transaction,
    sign,
    send_reliable_submission,
)

# ─── CONFIGURATION ────────────────────────────────────────────────────

# XRPL RPC URL (Testnet default; override via env var for Mainnet)
RPC_URL = os.getenv(
    "XRPL_RPC_URL",
    "https://s.altnet.rippletest.net:51234"
)
client = JsonRpcClient(RPC_URL)

# Load signer seeds from environment variables
ISSUER_SEED   = os.getenv("ISSUER_SEED")
SIGNER1_SEED  = os.getenv("SIGNER1_SEED")
SIGNER2_SEED  = os.getenv("SIGNER2_SEED")
# (Optionally: add SIGNER3_SEED, SIGNER4_SEED)

# Instantiate XRPL Wallets
issuer_wallet  = Wallet(seed=ISSUER_SEED)
signer1_wallet = Wallet(seed=SIGNER1_SEED)
signer2_wallet = Wallet(seed=SIGNER2_SEED)

# Your custom token’s 40-char hex code for “RCQ-TBILL”
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
    """
    Mint RCQ-TBILL tokens via a 2-of-4 multisig issuer account.
    """
    try:
        # 1) Build the base Payment transaction (single-sign template)
        payment_tx = Payment(
            account=issuer_wallet.classic_address,
            destination=issuer_wallet.classic_address,  # or pass in a req.destination
            amount=IssuedCurrencyAmount(
                currency=CURRENCY_HEX,
                issuer=issuer_wallet.classic_address,
                value=str(req.amount),
            ),
        )

        # 2) Autofill fee & sequence using the issuer wallet
        filled_tx = safe_sign_and_autofill_transaction(
            payment_tx, issuer_wallet, client
        )

        # 3) Each signer applies a multisignature
        sig1 = sign(filled_tx, signer1_wallet, multisign=True)
        sig2 = sign(filled_tx, signer2_wallet, multisign=True)

        # 4) Combine signatures into a MultiSignedTransaction
        combined_signers = sig1.tx_json["Signers"] + sig2.tx_json["Signers"]
        multisigned = MultiSignedTransaction.from_dict({
            **filled_tx.to_dict(),
            "Signers": combined_signers
        })

        # 5) Submit the multisigned envelope and wait for validation
        resp = send_reliable_submission(multisigned, client)
        result = resp.result

        if result.get("engine_result") != "tesSUCCESS":
            raise HTTPException(
                status_code=500,
                detail=f"XRPL error: {result.get('engine_result')}"
            )

        # Return the transaction hash on success
        return MintResponse(
            status="success",
            tx_hash=result["tx_json"]["hash"]
        )

    except Exception as e:
        # Bubble up any errors as a 500
        raise HTTPException(status_code=500, detail=f"Mint failed: {e}")

