# Financial Services Domain Model

## Overview

A financial services organization manages a complex network of entities including customers, accounts, transactions, financial products, regulatory compliance, and risk management. This document describes the core domain model for a universal banking operation encompassing retail banking, corporate banking, investment services, and insurance.

## Customers

A **Customer** is a person or organization that holds one or more accounts or subscribes to products offered by the institution. Customers are classified into two primary subtypes:

### Individual Customer

An **Individual Customer** is a natural person identified by:
- Full legal name (first, middle, last) and any aliases or former names
- Date of birth and gender
- National identification number (SSN, national ID, passport number)
- Tax identification number and tax residency jurisdiction
- Contact information: primary email, secondary email, mobile phone, home phone, mailing address, residential address
- Employment information: employer name, job title, annual income, employment status (employed, self-employed, retired, student, unemployed)
- Credit score (FICO or equivalent) updated periodically
- Risk rating (low, medium, high) based on transaction patterns and credit history
- Customer segment: mass market, affluent, high-net-worth (HNW), ultra-high-net-worth (UHNW)
- Preferred communication channel: email, SMS, phone, mail
- Digital banking enrollment status and last login timestamp

### Corporate Customer

A **Corporate Customer** is a legal entity identified by:
- Legal entity name and any trading names or DBAs (doing business as)
- Legal entity identifier (LEI) — a 20-character alphanumeric code
- Company registration number and jurisdiction of incorporation
- Industry sector (NAICS or SIC code) and sub-sector
- Company size: micro, small, medium, large, enterprise
- Annual revenue and number of employees
- Incorporation date and fiscal year end
- Registered address and principal place of business
- Ultimate beneficial owners (UBOs) — individuals who own ≥25% of the entity
- Authorized signatories with their signing authority limits
- Parent company and subsidiary relationships (corporate hierarchy)
- Assigned relationship manager (an Employee of the institution)
- Credit facility limits and utilization

### Customer Lifecycle

Every customer progresses through a lifecycle:
1. **Prospect** — identified potential customer, not yet onboarded
2. **Application** — submitted an account opening or product application
3. **Onboarding** — undergoing KYC/AML verification
4. **Active** — fully onboarded with active accounts
5. **Dormant** — no transactions for >12 months
6. **Closed** — all accounts closed, relationship terminated
7. **Deceased/Dissolved** — for individuals who have died or entities that have been dissolved

KYC (Know Your Customer) verification status can be: pending, in-progress, verified, expired, or failed. KYC must be renewed periodically (typically every 1-3 years depending on risk rating).

## Accounts

An **Account** is a financial record maintained by the institution for a customer. Accounts have:
- Account number (IBAN or domestic format)
- Account name and description
- Account opening date and maturity date (if applicable)
- Currency (ISO 4217 code) — multicurrency accounts hold balances in multiple currencies
- Current balance, available balance, and ledger balance
- Status: active, dormant, frozen, suspended, closed
- Branch code and associated branch
- Interest accrual method: daily, monthly, quarterly

### Account Subtypes

**Checking Account (Current Account):**
- Overdraft facility: approved limit, interest rate on overdraft, current overdraft balance
- Associated debit card(s) with card number, expiration, and daily spending limit
- Check writing privileges with next check number
- Monthly maintenance fee and fee waiver conditions
- Direct deposit enrollment

**Savings Account:**
- Annual interest rate (APY) — may be tiered based on balance
- Minimum balance requirement and penalty for going below
- Maximum monthly withdrawal count (Regulation D compliance in the US)
- Compounding frequency: daily, monthly, quarterly, annually
- Promotional rate period and standard rate after promotion

**Money Market Account:**
- Tiered interest rates based on balance thresholds
- Check writing and debit card access (limited)
- Minimum opening deposit and minimum balance for interest earning

**Certificate of Deposit (CD) / Term Deposit:**
- Principal amount deposited
- Fixed interest rate and term (3 months, 6 months, 1 year, 2 years, 5 years)
- Maturity date and auto-renewal instructions
- Early withdrawal penalty calculation method
- Callable or non-callable flag

**Investment Account (Brokerage Account):**
- Portfolio of financial instruments (equities, bonds, ETFs, options, futures)
- Risk profile: conservative, moderate, aggressive, speculative
- Investment strategy: growth, income, balanced, capital preservation
- Assigned investment advisor (a licensed professional)
- Margin account flag and margin utilization
- Annual portfolio return and benchmark comparison

**Loan Account:**
- Principal amount and disbursement date
- Interest rate: fixed or variable (variable rates tied to a reference rate like SOFR or prime)
- Loan term in months and remaining term
- Repayment schedule: monthly payment amount, next payment due date
- Amortization method: equal installments, balloon, interest-only, graduated
- Collateral: type (real estate, vehicle, securities, cash), valuation amount, valuation date, lien position
- Loan-to-value (LTV) ratio
- Current delinquency status and days past due
- Loan origination fee and other charges

**Credit Card Account:**
- Credit limit and available credit
- Current statement balance and minimum payment due
- Annual percentage rate (APR) for purchases, balance transfers, and cash advances
- Rewards program: type (cashback, points, miles), accumulated rewards, redemption rate
- Billing cycle dates and payment due date
- Annual fee and fee waiver conditions
- Authorized additional cardholders

## Transactions

A **Transaction** records any financial event affecting an account balance. Every transaction has:
- Transaction ID (globally unique)
- Transaction date and time (UTC)
- Value date (settlement date)
- Amount and currency
- Debit/credit indicator
- Transaction status: pending, posted, completed, failed, reversed, disputed
- Transaction channel: branch, ATM, online banking, mobile app, wire, ACH, POS
- Merchant or counterparty information
- Narrative/description and reference number
- Running balance after transaction

### Transaction Types

**Deposit:** Funds added to an account from an external source. May be cash, check, wire transfer, or ACH. Check deposits may have a hold period based on the check amount and customer relationship.

**Withdrawal:** Funds removed from an account via cash withdrawal, ATM, or wire transfer. Subject to daily withdrawal limits and available balance checks.

**Internal Transfer:** Movement of funds between accounts held at the same institution. Immediate settlement. Source and destination accounts must belong to the same customer or have authorized transfer permissions.

**External Transfer (Wire/ACH):** Movement of funds to accounts at other institutions. Wire transfers are typically same-day; ACH transfers take 1-3 business days. Includes SWIFT/BIC codes for international wires.

**Bill Payment:** Scheduled or one-time payment to a registered biller (utility, credit card, mortgage). Has a payee name, payee account number, and payment reference.

**Point of Sale (POS) Payment:** Debit or credit card transaction at a merchant. Includes merchant name, merchant category code (MCC), terminal ID, and authorization code.

**Fee:** A charge levied by the institution — monthly maintenance fee, overdraft fee, wire transfer fee, ATM fee, etc. Linked to a Fee Schedule that defines fee types and amounts.

**Interest Posting:** Periodic credit (for deposit accounts) or debit (for loan accounts) of accrued interest. Calculated based on the account's interest rate and accrual method.

**Dividend/Distribution:** Payment received from investment holdings — stock dividends, bond coupon payments, mutual fund distributions. Classified as ordinary income, qualified dividends, or return of capital.

## Financial Products

A **Financial Product** is an offering provided by the institution to its customers. Products have:
- Product code (unique identifier) and version number
- Product name and marketing description
- Product category: deposit, lending, investment, insurance, cards, payments
- Eligibility criteria: minimum age, minimum income, credit score threshold, geographic restrictions
- Terms and conditions document reference
- Effective date and discontinuation date
- Pricing: base rate, spread, fee schedule
- Associated regulatory requirements

### Product Subtypes

**Mortgage:**
- Property type: residential, commercial, agricultural, construction
- Loan-to-value (LTV) ratio limits
- Rate type: fixed (15yr, 30yr), adjustable (ARM with adjustment period), interest-only
- Property valuation: appraised value, appraisal date, appraiser
- Title insurance requirement and title search status
- Escrow account for taxes and insurance
- Private mortgage insurance (PMI) requirement and monthly PMI premium

**Insurance Policy:**
- Coverage type: life, health, property, casualty, auto, liability, umbrella, professional indemnity
- Policy term: annual, multi-year, whole life
- Premium amount and payment frequency
- Coverage amount (sum insured) and deductible
- Named insured, additional insured, and beneficiary designations
- Exclusions and special conditions
- Claims history: number of claims, total amount paid

**Mutual Fund / Investment Fund:**
- Fund name, ticker symbol, and CUSIP/ISIN
- Fund manager and management company
- Net asset value (NAV) per share (updated daily)
- Expense ratio (annual management fee)
- Asset class: equity, fixed income, balanced, money market, alternative
- Geographic focus: domestic, international, global, emerging markets
- Investment style: value, growth, blend
- Minimum initial investment and minimum subsequent investment
- Distribution policy: accumulating or distributing
- Morningstar rating and performance benchmarks

**Structured Product / Derivative:**
- Underlying asset or index
- Notional amount and maturity date
- Payoff structure: capital protected, leveraged, income-generating
- Counterparty risk and credit support annex (CSA) terms
- Mark-to-market valuation and collateral requirements

## Organizational Structure

The institution itself has a complex organizational structure:

**Branch:** A physical location offering banking services. Has a branch code, name, address, phone number, operating hours, and branch manager. Branches belong to a Region.

**Region:** A geographic grouping of branches managed by a Regional Director. Regions belong to a Division.

**Division:** A business unit (e.g., Retail Banking, Corporate Banking, Wealth Management, Investment Banking). Each division has a Division Head and P&L responsibility.

**Department:** A functional unit within a division (e.g., Credit Risk, Compliance, Operations, IT). Departments have cost centers.

**Employee:** A staff member of the institution with employee ID, name, role, department, hire date, and reporting manager. Employees may hold licenses (Series 7, Series 63, insurance licenses).

## Regulatory and Compliance

**Regulatory Body:** An external authority (e.g., OCC, FDIC, SEC, FINRA, FCA, ECB, BaFin) that oversees the institution.

**Regulation:** A specific law or rule (e.g., Dodd-Frank Act, Basel III, GDPR, PSD2, MiFID II) with an effective date, jurisdiction, and applicable business areas.

**Compliance Requirement:** An actionable item derived from a regulation — a control, reporting obligation, or operational procedure that must be followed.

**Regulatory Report:** A periodic filing submitted to a regulatory body (e.g., Call Report, FR Y-9C, SAR, CTR). Has a report type, reporting period, submission deadline, and filing status.

**Audit:** An internal or external examination of processes, controls, or financial statements. Has an audit type, scope, findings, and remediation plan.

## Risk Management

**Credit Risk Assessment:** Evaluation of a borrower's ability to repay. Includes probability of default (PD), loss given default (LGD), exposure at default (EAD), and expected loss (EL).

**Market Risk Measure:** Quantification of potential loss from market movements — Value at Risk (VaR), stress test results, sensitivity analysis (duration, convexity for bonds; delta, gamma for options).

**Operational Risk Event:** An incident caused by internal process failure, human error, system failure, or external event. Categorized by Basel II event type (internal fraud, external fraud, employment practices, clients/products, damage to assets, business disruption, execution/delivery).

**Liquidity Risk Metric:** Measures of the institution's ability to meet short-term obligations — Liquidity Coverage Ratio (LCR), Net Stable Funding Ratio (NSFR), cash flow projections.

**Fraud Alert:** A flagged suspicious activity with alert type (identity theft, account takeover, card fraud, wire fraud), severity, investigation status (open, investigating, escalated, closed), and resolution (confirmed fraud, false positive).

**Sanctions Screening Result:** Outcome of screening a customer or transaction against sanctions lists (OFAC SDN, EU sanctions, UN sanctions). Result: clear, potential match, confirmed match.

## Relationships Summary

- A Customer **holds** one or more Accounts
- An Account **contains** Transactions
- A Customer **subscribes to** Financial Products
- A Loan Account **is secured by** Collateral
- A Corporate Customer **is managed by** a Relationship Manager (Employee)
- A Corporate Customer **has subsidiaries** (other Corporate Customers)
- A Corporate Customer **has beneficial owners** (Individual Customers)
- An Investment Account **is advised by** an Investment Advisor (Employee)
- A Transfer Transaction **debits** a source Account and **credits** a destination Account
- A Financial Product **is subject to** Compliance Requirements
- A Compliance Requirement **is derived from** a Regulation
- A Regulation **is issued by** a Regulatory Body
- A Risk Assessment **is performed on** Customers and Accounts
- A Fraud Alert **is triggered by** a Transaction
- A Branch **belongs to** a Region **belongs to** a Division
- An Employee **works at** a Branch and **reports to** a Manager (another Employee)
- An Employee **holds** Licenses and **belongs to** a Department
- A Regulatory Report **is filed with** a Regulatory Body
- An Audit **examines** Departments or Branches
