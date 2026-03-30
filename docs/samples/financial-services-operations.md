# Financial Services Operations and Processes

## Overview

This document describes the operational processes, workflows, and service delivery mechanisms within a financial services institution. It complements the domain model by defining how entities interact through business processes.

## Customer Onboarding Process

The **Customer Onboarding Process** is a regulated workflow that transforms a prospect into an active customer:

### Application Intake

An **Application** is submitted through any channel (branch, online, mobile, phone). The application captures:
- Applicant personal information (name, DOB, address, identification documents)
- Requested products and services
- Source of funds declaration
- Consent to terms and conditions, privacy policy, and electronic communications
- Referral source (existing customer, marketing campaign, branch walk-in, online search)

### Identity Verification

**Identity Verification** validates the applicant's claimed identity through:
- **Document Verification** — scanning and validating government-issued ID (passport, driver's license, national ID card). Checks for document authenticity, expiration, and name/photo match.
- **Biometric Verification** — facial recognition comparing selfie to ID photo, fingerprint matching, or voice recognition.
- **Address Verification** — utility bill, bank statement, or government letter confirming residential address. Must be dated within the last 3 months.
- **Electronic Verification** — automated checks against credit bureaus, electoral rolls, and government databases.

### KYC/AML Screening

**KYC Assessment** determines the customer's risk profile:
- **Sanctions Screening** — checking the applicant against OFAC SDN, EU consolidated sanctions list, UN sanctions, and country-specific lists.
- **PEP Screening** — determining if the applicant is a Politically Exposed Person (current or former government official, senior political figure, or close associate/family member).
- **Adverse Media Screening** — searching news sources for negative coverage (fraud, corruption, money laundering, terrorism financing).
- **Risk Scoring** — algorithmic assessment combining factors: country risk, occupation risk, expected transaction volume, product risk, source of wealth.

A **Customer Risk Profile** is generated with a risk category (low, medium, high, prohibited) and determines:
- Enhanced Due Diligence (EDD) requirements for high-risk customers
- Transaction monitoring thresholds
- Periodic review frequency (annually for high risk, every 3 years for low risk)

### Account Opening

Once KYC is approved, the **Account Opening** process:
- Creates customer record in the core banking system
- Opens requested accounts with initial funding
- Issues access credentials (online banking, mobile app)
- Orders physical items (debit cards, checkbooks)
- Sets up standing instructions (direct debits, recurring transfers)
- Triggers welcome communication sequence

## Payment Processing

### Domestic Payments

**ACH Payment Processing:**
An ACH payment passes through multiple stages:
1. **Origination** — the paying customer or institution creates a payment instruction
2. **Batching** — individual payments are collected into batches by the ACH operator
3. **Clearing** — the ACH network (e.g., Federal Reserve, EPN) processes batches and calculates net settlement positions
4. **Settlement** — funds are transferred between institutions at the Federal Reserve
5. **Posting** — the receiving institution credits the payee's account

An **ACH Batch** contains multiple **ACH Entries**, each with an entry class code (PPD for consumer, CCD for corporate, WEB for internet-initiated), routing number, account number, amount, and addenda records.

**Real-Time Payments (RTP):**
RTP messages are processed individually (not batched):
- Instant payment initiation with immediate confirmation
- 24/7/365 availability
- Irrevocable once confirmed
- Maximum transaction limit applies
- Uses ISO 20022 message format

### International Payments

**SWIFT Wire Transfer:**
International payments use the SWIFT network:
- **MT103** — single customer credit transfer message
- **Ordering Customer** (payer) and **Beneficiary Customer** (payee)
- **Ordering Institution** (sending bank) and **Beneficiary Institution** (receiving bank)
- **Correspondent Banks** — intermediary banks when no direct relationship exists
- **Charges** — SHA (shared), OUR (payer bears all), BEN (beneficiary bears all)
- **Nostro/Vostro Accounts** — accounts held between correspondent banks for settlement
- **SWIFT GPI** tracking — provides end-to-end payment tracking with a unique end-to-end transaction reference (UETR)

**Foreign Exchange (FX):**
Cross-currency payments involve:
- **Spot Rate** — the current market exchange rate for immediate delivery
- **Forward Rate** — a locked-in rate for future delivery (used for hedging)
- **FX Spread** — the difference between buy and sell rates (the institution's margin)
- **FX Deal** — a transaction to buy/sell a currency pair at a specific rate

## Lending Operations

### Loan Origination

The **Loan Origination Process** transforms a loan application into a funded loan:

1. **Pre-Qualification** — preliminary assessment of borrower eligibility based on income, credit score, and existing debt (debt-to-income ratio)
2. **Application** — formal loan application with detailed financial information, purpose of loan, and requested terms
3. **Credit Analysis** — in-depth evaluation including:
   - **Financial Statement Analysis** — review of income statements, balance sheets, cash flow statements (for commercial loans)
   - **Collateral Appraisal** — independent valuation of pledged collateral
   - **Industry Analysis** — assessment of the borrower's industry outlook and competitive position
   - **Cash Flow Projection** — modeling the borrower's ability to service the debt
4. **Credit Decision** — approval, conditional approval, or decline. For amounts above delegated authority, escalation to a **Credit Committee**
5. **Documentation** — preparation and execution of loan agreement, promissory note, security agreement, and personal/corporate guarantees
6. **Disbursement** — funding the loan to the borrower's account
7. **Booking** — recording the loan in the core banking system with all terms and conditions

### Loan Servicing

**Loan Servicing** manages the ongoing lifecycle of a loan:
- **Payment Processing** — receiving and applying borrower payments (principal, interest, escrow)
- **Statement Generation** — monthly or periodic statements showing balance, payments received, and upcoming payments
- **Escrow Management** — holding and disbursing funds for property taxes and insurance (for mortgages)
- **Rate Adjustment** — recalculating payments for variable-rate loans when the reference rate changes
- **Delinquency Management** — tracking past-due payments, sending late notices, assessing late fees
- **Modification/Restructuring** — adjusting loan terms for borrowers in financial difficulty (forbearance, term extension, rate reduction)
- **Payoff Processing** — calculating the payoff amount and processing early repayment
- **Loan Participation** — selling a portion of the loan to other institutions to manage concentration risk

## Investment Operations

### Trade Lifecycle

A **Securities Trade** passes through the following stages:
1. **Order Placement** — client instructs the institution to buy or sell a security. Order types: market, limit, stop, stop-limit
2. **Order Routing** — the order is sent to a trading venue (stock exchange, dark pool, over-the-counter market)
3. **Execution** — the order is filled (fully or partially) at a specific price. An **Execution Report** confirms the fill price, quantity, and venue
4. **Confirmation** — trade details are confirmed with the counterparty
5. **Clearing** — a **Clearinghouse** (e.g., DTCC, Euroclear) acts as central counterparty, netting obligations
6. **Settlement** — delivery of securities versus payment (DVP). Standard settlement: T+1 for US equities, T+2 for most international markets
7. **Custody** — securities are held in a **Custody Account** at a custodian bank or central securities depository

### Corporate Actions

**Corporate Actions** are events initiated by a public company that affect its shareholders:
- **Dividend** — cash or stock distribution to shareholders. Record date, ex-dividend date, payment date.
- **Stock Split** — increase in shares outstanding (e.g., 2-for-1). Adjustment of position quantity and cost basis.
- **Rights Issue** — offering of additional shares to existing shareholders at a discount
- **Merger/Acquisition** — conversion of shares in the target company to shares or cash in the acquirer
- **Tender Offer** — invitation to shareholders to sell their shares at a specified price
- **Spin-Off** — distribution of shares in a newly independent company to existing shareholders

### Portfolio Management

A **Portfolio** is a collection of investment positions managed according to an **Investment Policy Statement (IPS)**:
- **Asset Allocation** — target percentages for each asset class (equities, fixed income, alternatives, cash)
- **Rebalancing** — periodic adjustment of holdings to maintain target allocation. Triggers: calendar-based, threshold-based (drift > 5%), tactical
- **Performance Measurement** — time-weighted return (TWR), money-weighted return (MWR), comparison to benchmark indices
- **Risk Metrics** — portfolio VaR, tracking error, Sharpe ratio, Sortino ratio, maximum drawdown

## Anti-Money Laundering (AML) Operations

### Transaction Monitoring

**Transaction Monitoring** is the automated surveillance of customer transactions to detect suspicious activity:

**Monitoring Rules** define patterns that trigger alerts:
- **Structuring** — multiple transactions just below reporting thresholds (e.g., multiple cash deposits of $9,900 to avoid $10,000 CTR filing)
- **Rapid Movement** — funds received and immediately transferred to another institution or country
- **Unusual Pattern** — transaction volume or amounts significantly deviating from the customer's historical profile
- **High-Risk Geography** — transactions involving countries on the FATF grey or black list
- **Round-Trip** — funds sent out and returned through a different channel or entity (layering)

### Suspicious Activity Reporting

When a **Suspicious Activity Report (SAR)** is warranted:
1. **Alert Generation** — the monitoring system generates an alert
2. **Alert Triage** — a Level 1 analyst reviews the alert and determines if investigation is needed
3. **Investigation** — a Level 2 analyst conducts a thorough review of the customer's activity, including gathering additional documentation
4. **Decision** — determination to file a SAR, escalate, or dismiss the alert with justification
5. **Filing** — SAR is filed with FinCEN (in the US) within 30 days of detection. Contains narrative description, subject information, and suspicious activity details
6. **Case Closure** — documentation of the investigation outcome and any follow-up actions (account restriction, relationship termination, law enforcement referral)

### Currency Transaction Reporting

A **Currency Transaction Report (CTR)** must be filed for any cash transaction exceeding $10,000 (or equivalent). Multiple transactions by the same customer that aggregate to over $10,000 in a single day must also be reported.

## Reconciliation and Settlement

**Reconciliation** is the process of comparing two sets of records to ensure consistency:
- **Account Reconciliation** — comparing the institution's internal ledger to external statements (e.g., nostro account reconciliation with correspondent banks)
- **Trade Reconciliation** — matching trade details between the institution and its counterparties
- **Cash Reconciliation** — balancing physical cash counts with system records (for branches and ATMs)
- **GL Reconciliation** — ensuring general ledger balances match subsidiary ledger totals

A **Reconciliation Break** is a discrepancy that must be investigated and resolved. Breaks have:
- Aging (days outstanding)
- Root cause category (timing difference, booking error, missing entry, duplicate entry)
- Resolution action and responsible party
- Materiality threshold for escalation
