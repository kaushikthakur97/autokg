"""
Insurance Dataset Generator — Synthea-inspired schema
======================================================
Generates 12 interconnected tables simulating a P&C insurance carrier's data lake.
All relationships are explicit — perfect for autokg testing.
"""
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl

random.seed(42)

OUTPUT_DIR = Path("silver_insurance")
OUTPUT_DIR.mkdir(exist_ok=True)

NUM_POLICYHOLDERS = 200
NUM_AGENTS = 20
NUM_UNDERWRITERS = 10
NUM_POLICIES = 300
NUM_CLAIMS = 400
NUM_PAYMENTS = 600
NUM_REINSURANCE_TREATIES = 8
MAX_COVERAGES_PER_POLICY = 4

countries = ["US", "US", "US", "US", "US", "CA", "UK", "DE", "FR", "AU", "JP", "BR", "MX", "IN"]
states = ["CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA", "ON", "BC"]
cities = ["Springfield", "Riverside", "Oakwood", "Lakeview", "Hillcrest", "Brookfield", "Westfield", "Northgate"]
industries = ["Manufacturing", "Retail", "Technology", "Healthcare", "Construction", "Logistics", "Finance", "Real Estate", "Agriculture", "Energy"]
risk_levels = ["low", "medium", "high", "critical"]
claim_statuses = ["submitted", "under_review", "approved", "denied", "partially_paid", "paid", "closed", "appealed"]
payment_methods = ["ACH", "wire", "check", "credit_card", "direct_deposit"]
coverage_types = ["Liability", "Property", "Auto", "Workers Comp", "Cyber", "D&O", "Business Interruption", "Professional Liability"]
policy_statuses = ["active", "active", "active", "active", "expired", "cancelled", "pending", "lapsed"]
fraud_flags = [None, None, None, None, None, None, None, "soft_flag", "hard_flag", "investigation"]
insurance_lines = ["Commercial P&C", "Personal Auto", "Homeowners", "Commercial Auto", "General Liability", "Umbrella"]
canonical_codes = ["CP-001", "PA-002", "HO-003", "CA-004", "GL-005", "UM-006"]

print("=" * 60)
print("GENERATING INSURANCE DATASET — 12 Tables")
print("=" * 60)

# ── 1. Policyholders ──
print("[ 1/12] Policyholders...")
policyholders = pl.DataFrame({
    "policyholder_id": list(range(1, NUM_POLICYHOLDERS + 1)),
    "first_name": [random.choice(["James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda","David","Elizabeth","William","Barbara","Richard","Susan","Joseph","Jessica"]) for _ in range(NUM_POLICYHOLDERS)],
    "last_name": [random.choice(["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson"]) for _ in range(NUM_POLICYHOLDERS)],
    "email": [f"ph{i}@insurance.demo" for i in range(1, NUM_POLICYHOLDERS + 1)],
    "phone": [f"+1-555-{random.randint(1000,9999)}" for _ in range(NUM_POLICYHOLDERS)],
    "city": [random.choice(cities) for _ in range(NUM_POLICYHOLDERS)],
    "state": [random.choice(states) for _ in range(NUM_POLICYHOLDERS)],
    "country": [random.choice(countries) for _ in range(NUM_POLICYHOLDERS)],
    "industry": [random.choice(industries) if random.random() > 0.3 else None for _ in range(NUM_POLICYHOLDERS)],
    "credit_score": [random.randint(300, 850) for _ in range(NUM_POLICYHOLDERS)],
    "years_as_customer": [random.randint(0, 25) for _ in range(NUM_POLICYHOLDERS)],
    "created_at": [datetime(2020, 1, 1) + timedelta(days=random.randint(0, 1500)) for _ in range(NUM_POLICYHOLDERS)],
})
policyholders.write_parquet(OUTPUT_DIR / "policyholders.parquet")
print(f"  -> {policyholders.height} rows, {len(policyholders.columns)} columns")

# ── 2. Agents ──
print("[ 2/12] Agents...")
agents = pl.DataFrame({
    "agent_id": list(range(1, NUM_AGENTS + 1)),
    "first_name": [random.choice(["Alice","Bob","Carol","Dan","Eve","Frank","Grace","Henry","Iris","Jack","Kate","Leo","Mia","Noah","Olivia","Peter","Quinn","Rose","Sam","Tina"]) for _ in range(NUM_AGENTS)],
    "last_name": [random.choice(["Anderson","Brooks","Chen","Diaz","Evans","Foster","Gupta","Hayes","Ito","Jensen"]) for _ in range(NUM_AGENTS)],
    "email": [f"agent{i}@insurance.demo" for i in range(1, NUM_AGENTS + 1)],
    "license_number": [f"LIC-{random.randint(10000,99999)}" for _ in range(NUM_AGENTS)],
    "region": [random.choice(["Northeast","Southeast","Midwest","Southwest","West"]) for _ in range(NUM_AGENTS)],
    "commission_rate": [round(random.uniform(0.05, 0.20), 3) for _ in range(NUM_AGENTS)],
    "is_active": [random.random() > 0.1 for _ in range(NUM_AGENTS)],
})
agents.write_parquet(OUTPUT_DIR / "agents.parquet")
print(f"  -> {agents.height} rows, {len(agents.columns)} columns")

# ── 3. Underwriters ──
print("[ 3/12] Underwriters...")
underwriters = pl.DataFrame({
    "underwriter_id": list(range(1, NUM_UNDERWRITERS + 1)),
    "name": [f"UW-{random.choice(['Alpha','Beta','Gamma','Delta','Epsilon','Zeta','Eta','Theta','Iota','Kappa'])}" for _ in range(NUM_UNDERWRITERS)],
    "specialization": [random.choice(["Property","Casualty","Marine","Cyber","Life","Health","Reinsurance"]) for _ in range(NUM_UNDERWRITERS)],
    "authority_limit": [random.choice([100000, 250000, 500000, 1000000, 2500000, 5000000]) for _ in range(NUM_UNDERWRITERS)],
})
underwriters.write_parquet(OUTPUT_DIR / "underwriters.parquet")
print(f"  -> {underwriters.height} rows, {len(underwriters.columns)} columns")

# ── 4. Policies ──
print("[ 4/12] Policies...")
policies = pl.DataFrame({
    "policy_id": list(range(1, NUM_POLICIES + 1)),
    "policyholder_id": [random.randint(1, NUM_POLICYHOLDERS) for _ in range(NUM_POLICIES)],
    "agent_id": [random.randint(1, NUM_AGENTS) for _ in range(NUM_POLICIES)],
    "underwriter_id": [random.randint(1, NUM_UNDERWRITERS) for _ in range(NUM_POLICIES)],
    "policy_number": [f"POL-{2020 + random.randint(0,5)}-{random.randint(10000,99999)}" for _ in range(NUM_POLICIES)],
    "insurance_line": [random.choice(insurance_lines) for _ in range(NUM_POLICIES)],
    "canonical_product_code": [random.choice(canonical_codes) for _ in range(NUM_POLICIES)],
    "status": [random.choice(policy_statuses) for _ in range(NUM_POLICIES)],
    "premium_amount": [round(random.uniform(500, 50000), 2) for _ in range(NUM_POLICIES)],
    "deductible": [random.choice([500, 1000, 2500, 5000, 10000, 25000]) for _ in range(NUM_POLICIES)],
    "effective_date": [datetime(2020, 1, 1) + timedelta(days=random.randint(0, 1800)) for _ in range(NUM_POLICIES)],
    "expiration_date": [None] * NUM_POLICIES,
    "cancellation_date": [None if random.random() > 0.1 else (datetime(2021, 1, 1) + timedelta(days=random.randint(0, 1200))) for _ in range(NUM_POLICIES)],
    "risk_level": [random.choice(risk_levels) for _ in range(NUM_POLICIES)],
})
policies = policies.with_columns(
    pl.col("effective_date").cast(pl.Date).alias("effective_date"),
)
policies = policies.with_columns(
    pl.when(pl.col("status").is_in(["expired", "cancelled"]))
    .then(pl.col("effective_date") + pl.duration(days=365))
    .otherwise(None)
    .alias("expiration_date"),
)
policies.write_parquet(OUTPUT_DIR / "policies.parquet")
print(f"  -> {policies.height} rows, {len(policies.columns)} columns")

# ── 5. Coverages ──
print("[ 5/12] Coverages...")
coverages = []
cov_id = 1
for pid in range(1, NUM_POLICIES + 1):
    num_cov = random.randint(1, MAX_COVERAGES_PER_POLICY)
    chosen = random.sample(coverage_types, num_cov)
    for ct in chosen:
        coverages.append({
            "coverage_id": cov_id,
            "policy_id": pid,
            "coverage_type": ct,
            "limit_amount": random.choice([50000, 100000, 250000, 500000, 1000000, 2000000, 5000000]),
            "sub_limit": random.choice([10000, 25000, 50000, 100000, None, None]),
            "deductible_per_claim": random.choice([0, 500, 1000, 2500, 5000]),
            "coinsurance_pct": random.choice([0, 10, 20, None, None, None]),
        })
        cov_id += 1
coverages_df = pl.DataFrame(coverages)
coverages_df.write_parquet(OUTPUT_DIR / "coverages.parquet")
print(f"  -> {coverages_df.height} rows, {len(coverages_df.columns)} columns")

# ── 6. Claims ──
print("[ 6/12] Claims...")
claims_data = []
for i in range(1, NUM_CLAIMS + 1):
    pid = random.randint(1, NUM_POLICIES)
    claim_date = datetime(2021, 1, 1) + timedelta(days=random.randint(0, 1400))
    resolved_date = claim_date + timedelta(days=random.randint(5, 180)) if random.random() > 0.3 else None
    reported_amount = round(random.uniform(500, 250000), 2)
    paid_amount = round(reported_amount * random.uniform(0, 1.3), 2) if resolved_date else None
    claims_data.append({
        "claim_id": i,
        "policy_id": pid,
        "claim_number": f"CLM-{claim_date.year}-{random.randint(10000,99999)}",
        "claim_date": claim_date,
        "reported_by": random.choice(["policyholder", "agent", "third_party", "auto_alert"]),
        "claim_description": random.choice([
            "Water damage from burst pipe", "Vehicle collision — rear end", "Fire damage to warehouse",
            "Slip and fall — customer injury", "Cyber breach — data exposure", "Wind damage to roof",
            "Employee injury — lifting incident", "Theft of equipment", "Lightning strike damage",
            "Product liability claim", "Professional error — missed deadline", "Natural flood damage",
            "Vandalism — broken windows", "Business interruption — power outage", "Hail damage to fleet",
        ]),
        "reported_amount": reported_amount,
        "reserve_amount": round(reported_amount * random.uniform(0.5, 1.5), 2),
        "paid_amount": paid_amount,
        "status": random.choice(claim_statuses),
        "fraud_flag": random.choice(fraud_flags),
        "fraud_score": round(random.uniform(0, 1), 3),
        "resolved_date": resolved_date,
        "resolution_note": random.choice([None, None, None, "paid in full", "partial settlement", "denied — exclusion applies", "under investigation"]),
    })
claims_df = pl.DataFrame(claims_data)
claims_df.write_parquet(OUTPUT_DIR / "claims.parquet")
print(f"  -> {claims_df.height} rows, {len(claims_df.columns)} columns")

# ── 7. Payments ──
print("[ 7/12] Payments...")
payments_data = []
pmt_id = 1
for claim in claims_df.iter_rows(named=True):
    if claim["paid_amount"] and claim["paid_amount"] > 0:
        num_pmts = random.randint(1, 3)
        remaining = claim["paid_amount"]
        for j in range(num_pmts):
            amt = round(remaining / (num_pmts - j) * random.uniform(0.8, 1.0), 2) if j < num_pmts - 1 else round(remaining, 2)
            remaining -= amt
            payments_data.append({
                "payment_id": pmt_id,
                "claim_id": claim["claim_id"],
                "amount": max(amt, 1.0),
                "payment_date": (claim["resolved_date"] or claim["claim_date"]) + timedelta(days=random.randint(1, 60)),
                "method": random.choice(payment_methods),
                "reference": f"PMT-{pmt_id:06d}",
                "status": random.choice(["pending", "processed", "cleared", "failed"]),
            })
            pmt_id += 1
payments_df = pl.DataFrame(payments_data)
payments_df.write_parquet(OUTPUT_DIR / "payments.parquet")
print(f"  -> {payments_df.height} rows, {len(payments_df.columns)} columns")

# ── 8. Claim Adjusters ──
print("[ 8/12] Adjusters...")
adjusters = pl.DataFrame({
    "adjuster_id": list(range(1, 21)),
    "name": [f"Adjuster-{random.choice(['Alpha','Bravo','Charlie','Delta','Echo','Foxtrot','Golf','Hotel','India','Juliet'])}" for _ in range(20)],
    "specialization": [random.choice(["Property","Auto","Liability","Workers Comp","Cyber","General"]) for _ in range(20)],
    "region": [random.choice(["Northeast","Southeast","Midwest","Southwest","West"]) for _ in range(20)],
    "years_experience": [random.randint(1, 30) for _ in range(20)],
})
adjusters.write_parquet(OUTPUT_DIR / "adjusters.parquet")
print(f"  -> {adjusters.height} rows, {len(adjusters.columns)} columns")

# ── 9. Claim-Adjuster Assignments ──
print("[ 9/12] Claim-Adjuster Assignments...")
assignments = []
for claim in claims_df.iter_rows(named=True):
    if random.random() > 0.05:
        assignments.append({
            "assignment_id": len(assignments) + 1,
            "claim_id": claim["claim_id"],
            "adjuster_id": random.randint(1, 20),
            "assigned_date": claim["claim_date"],
            "completed_date": claim.get("resolved_date"),
        })
assignments_df = pl.DataFrame(assignments)
assignments_df.write_parquet(OUTPUT_DIR / "claim_assignments.parquet")
print(f"  -> {assignments_df.height} rows, {len(assignments_df.columns)} columns")

# ── 10. Reinsurance Treaties ──
print("[10/12] Reinsurance Treaties...")
treaties = pl.DataFrame({
    "treaty_id": list(range(1, NUM_REINSURANCE_TREATIES + 1)),
    "treaty_name": [f"Q{2020 + i//2}-{['Prop','Cas','Cyber','Marine'][i%4]}-Treaty" for i in range(NUM_REINSURANCE_TREATIES)],
    "reinsurer": [random.choice(["Swiss Re","Munich Re","Berkshire Hathaway","Lloyd's","Hannover Re","SCOR","Everest Re"]) for _ in range(NUM_REINSURANCE_TREATIES)],
    "cession_rate": [round(random.uniform(0.10, 0.90), 2) for _ in range(NUM_REINSURANCE_TREATIES)],
    "retention_limit": [random.choice([1000000, 2500000, 5000000, 10000000]) for _ in range(NUM_REINSURANCE_TREATIES)],
    "effective_date": [datetime(2021, 1, 1) + timedelta(days=random.randint(0, 900)) for _ in range(NUM_REINSURANCE_TREATIES)],
})
treaties.write_parquet(OUTPUT_DIR / "reinsurance_treaties.parquet")
print(f"  -> {treaties.height} rows, {len(treaties.columns)} columns")

# ── 11. Locations (Insured Properties / Assets) ──
print("[11/12] Locations...")
locations = []
loc_id = 1
for ph in policyholders.iter_rows(named=True):
    num_locations = random.randint(1, 3)
    for _ in range(num_locations):
        locations.append({
            "location_id": loc_id,
            "policyholder_id": ph["policyholder_id"],
            "address": f"{random.randint(100,9999)} {random.choice(['Main','Oak','Elm','Pine','Maple','Cedar','Birch'])} St",
            "city": ph["city"],
            "state": ph["state"],
            "zip": f"{random.randint(10000,99999)}",
            "building_type": random.choice(["Office","Warehouse","Retail","Residential","Industrial","Mixed Use"]),
            "square_footage": random.randint(500, 50000),
            "construction_year": random.randint(1950, 2025),
            "has_sprinkler": random.random() > 0.3,
            "has_alarm": random.random() > 0.2,
        })
        loc_id += 1
locations_df = pl.DataFrame(locations)
locations_df.write_parquet(OUTPUT_DIR / "locations.parquet")
print(f"  -> {locations_df.height} rows, {len(locations_df.columns)} columns")

# ── 12. Inspections ──
print("[12/12] Inspections...")
inspections = []
insp_id = 1
for loc in locations_df.iter_rows(named=True):
    if random.random() > 0.4:
        insp_date = datetime(2021, 1, 1) + timedelta(days=random.randint(0, 1200))
        inspections.append({
            "inspection_id": insp_id,
            "location_id": loc["location_id"],
            "inspector_name": random.choice(["Inspector A","Inspector B","Inspector C","Inspector D","Inspector E"]),
            "inspection_date": insp_date,
            "score": random.randint(1, 100),
            "findings": random.choice(["No issues","Minor repairs needed","Major hazard identified","Code violation","All clear"]),
            "recommendation": random.choice([None,"Increase premium","Require repairs","Non-renewal warning","No action"]),
        })
        insp_id += 1
inspections_df = pl.DataFrame(inspections)
inspections_df.write_parquet(OUTPUT_DIR / "inspections.parquet")
print(f"  -> {inspections_df.height} rows, {len(inspections_df.columns)} columns")

print("\n" + "=" * 60)
print("DATASET GENERATED")
print(f"  Tables: 12")
print(f"  Total rows: {sum([policyholders.height, agents.height, underwriters.height, policies.height, coverages_df.height, claims_df.height, payments_df.height, adjusters.height, assignments_df.height, treaties.height, locations_df.height, inspections_df.height])}")
print(f"  Location: {OUTPUT_DIR.absolute()}")
print("=" * 60)
