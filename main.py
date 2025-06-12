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

# ─── CONFIGURATION ─────────────────────────────────────────────────
RPC_URL = os.getenv(
    "XRPL_RPC_URL",
    "https://s.altnet.rippletest.net:51234"
)
client = JsonRpcClient(RPC_URL)

ISSUER_SEED  = os.getenv("ISSUER_SEED")
SIGNER1_SEED = os.getenv("SIGNER1_SEED")
SIGNER2_SEED = os.getenv("SIGNER2_SEED")
for key, val in [("ISSUER_SEED", ISSUER_SEED), ("SIGNER1_SEED", SIGNER1_SEED), ("SIGNER2_SEED", SIGNER2_SEED)]:
    if not val:
        raise RuntimeError(f"Missing environment variable: {key}")

issuer_wallet  = Wallet(ISSUER_SEED, 0)
signer1_wallet = Wallet(SIGNER1_SEED, 0)
signer2_wallet = Wallet(SIGNER2_SEED, 0)

CURRENCY_HEX = "5243512D5442494C4C0000000000000000000000"

# ─── Pydantic Models ─────────────────────────────────────────────────
class MintRequest(BaseModel):
    cusip: str
    amount: float
    date: str

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
        # 1) Get issuer sequence
        info = client.request(
            AccountInfo(account=issuer_wallet.classic_address, ledger_index="current")
        ).result
        seq = info["account_data"]["Sequence"]

        # 2) Build unsigned Payment
        amt = IssuedCurrencyAmount(
            currency=CURRENCY_HEX,
            issuer=issuer_wallet.classic_address,
            value=str(req.amount)
        )
        tx = Payment(
            account=issuer_wallet.classic_address,
            destination=issuer_wallet.classic_address,
            amount=amt,
            send_max=amt,
            sequence=seq,
            fee="12",
            signing_pub_key=""
        )

        # 3) Each signer signs the same tx
        sig1 = sign(tx, signer1_wallet, multisign=True)
        sig2 = sign(tx, signer2_wallet, multisign=True)

        # 4) Combine Signers
        s1 = sig1["tx_json"]["Signers"]
        s2 = sig2["tx_json"]["Signers"]
        multi_payload = {**tx.to_dict(), "Signers": s1 + s2}

        # 5) Submit
        resp = client.request(Submit(tx_json=multi_payload)).result
        if resp.get("engine_result") != "tesSUCCESS":
            raise HTTPException(500, f"XRPL error: {resp.get('engine_result')}")

        return MintResponse(status="success", tx_hash=resp["tx_json"]["hash"])
    except Exception as e:
        raise HTTPException(500, detail=f"Mint failed: {e}")




