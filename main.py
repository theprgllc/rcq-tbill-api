import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.transactions import Payment
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo, Submit
from xrpl.transaction import sign
from xrpl.core.binarycodec import encode

# ─── CONFIGURATION ─────────────────────────────────────────────────
RPC_URL = os.getenv(
    "XRPL_RPC_URL",
    "https://s.altnet.rippletest.net:51234"
)
client = JsonRpcClient(RPC_URL)

# Load and validate secret seeds
ISSUER_SEED   = os.getenv("ISSUER_SEED")
SIGNER1_SEED  = os.getenv("SIGNER1_SEED")
SIGNER2_SEED  = os.getenv("SIGNER2_SEED")
for key, val in [("ISSUER_SEED", ISSUER_SEED), ("SIGNER1_SEED", SIGNER1_SEED), ("SIGNER2_SEED", SIGNER2_SEED)]:
    if not val:
        raise RuntimeError(f"Missing environment variable: {key}")

# Initialize wallets with sequence placeholder
issuer_wallet  = Wallet(ISSUER_SEED, 0)
signer1_wallet = Wallet(SIGNER1_SEED, 0)
signer2_wallet = Wallet(SIGNER2_SEED, 0)

# RCQ-TBILL custom token code (40-character HEX)
CURRENCY_HEX = "5243512D5442494C4C0000000000000000000000"

# ─── Pydantic Models ─────────────────────────────────────────────────
class MintRequest(BaseModel):
    cusip: str
    amount: float
    date: str    # ISO 8601 date string

class MintResponse(BaseModel):
    status: str
    tx_hash: str

# ─── FastAPI App ────────────────────────────────────────────────────
app = FastAPI(title="RCQ-TBILL Multisig Issuance API")

@app.get("/")
async def root():
    return {"message": "RCQ-TBILL API is live. Use /docs for API."}

@app.post("/mint", response_model=MintResponse)
def mint_tbill(req: MintRequest):
    try:
        # 1) Fetch current sequence
        acct_info = client.request(
            AccountInfo(
                account=issuer_wallet.classic_address,
                ledger_index="current"
            )
        ).result
        sequence = acct_info["account_data"]["Sequence"]

        # 2) Build unsigned Payment transaction
        issued_amt = IssuedCurrencyAmount(
            currency=CURRENCY_HEX,
            issuer=issuer_wallet.classic_address,
            value=str(req.amount)
        )
        payment_tx = Payment(
            account=issuer_wallet.classic_address,
            destination=issuer_wallet.classic_address,
            amount=issued_amt,
            send_max=issued_amt,
            sequence=sequence,
            fee="12",
            signing_pub_key=""
        )

        # 3) Each signer signs the same tx
        sig1 = sign(payment_tx, signer1_wallet, multisign=True)
        sig2 = sign(payment_tx, signer2_wallet, multisign=True)

        # 4) Collect SignerEntry dicts
        signers = [entry.to_dict() for entry in sig1.signers] + [entry.to_dict() for entry in sig2.signers]

        # 5) Prepare multisigned payload
        multi_payload = {**payment_tx.to_dict(), "Signers": signers}

        # 6) Encode to transaction blob
        blob = encode(multi_payload)

        # 7) Submit via JSON-RPC using tx_blob
        submission = Submit(tx_blob=blob)
        resp = client.request(submission).result
        if resp.get("engine_result") != "tesSUCCESS":
            raise HTTPException(
                status_code=500,
                detail=f"XRPL error: {resp.get('engine_result')}"
            )

        return MintResponse(status="success", tx_hash=resp["tx_json"]["hash"])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mint failed: {e}")







