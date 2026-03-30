# Supply Chain Operations and Processes

## Overview

This document describes the operational processes, workflows, and management practices within supply chain operations. It complements the domain model by defining how supply chain entities interact through business processes including procurement cycles, manufacturing execution, warehouse operations, and logistics coordination.

## Procurement Process

### Sourcing and Supplier Selection

The **Sourcing Process** identifies and qualifies suppliers:

**Request for Quotation (RFQ):** A formal invitation to suppliers to bid on a requirement:
- Item specifications and quantities
- Required delivery schedule and location
- Quality requirements and certifications needed
- Commercial terms: payment terms, warranty, liability
- Submission deadline and evaluation criteria

**Supplier Evaluation:** Assessment of potential suppliers:
- **Technical Capability** — can they produce to specification? Facility audit, sample testing
- **Financial Stability** — credit check, financial statement analysis, D&B rating
- **Quality System** — ISO certification, quality manual review, process audit
- **Capacity and Lead Time** — can they meet volume and timing requirements?
- **Cost Competitiveness** — landed cost analysis including material, labor, tooling, freight, duties
- **Risk Assessment** — single-source risk, geopolitical risk, natural disaster exposure, labor relations
- **Sustainability** — environmental practices, labor conditions, conflict mineral policies

**Supplier Scorecard:** Ongoing performance measurement:
- On-time delivery rate (target: >95%)
- Quality acceptance rate (target: >99%)
- Cost variance vs. contract
- Responsiveness: time to acknowledge orders, time to resolve issues
- Innovation contribution: value engineering suggestions, new material proposals

### Purchase Requisition to Payment

The **Procure-to-Pay (P2P)** process:
1. **Purchase Requisition (PR)** — internal request for goods or services, approved by budget owner
2. **Sourcing** — selecting supplier and negotiating terms (may use existing contract)
3. **Purchase Order (PO)** — formal order sent to supplier
4. **Order Acknowledgment** — supplier confirms PO details and delivery commitment
5. **Advance Shipping Notice (ASN)** — supplier sends shipment details before goods arrive
6. **Goods Receipt** — receiving inspection at the warehouse, three-way match (PO, receipt, invoice)
7. **Invoice Receipt** — supplier invoice received and matched against PO and goods receipt
8. **Payment** — payment processed per agreed terms (check, ACH, wire)
9. **Reconciliation** — monthly reconciliation of supplier statements

## Manufacturing Execution

### Production Planning

**Master Production Schedule (MPS):** The top-level plan for what to produce:
- Planning horizon: typically 3-18 months
- Time buckets: weekly or monthly
- Planned production quantities by product and period
- Constrained by: available capacity, material availability, demand forecast

**Material Requirements Planning (MRP):** Explosion of the MPS through BOMs:
- **Gross Requirements** — total material needed based on MPS and BOM
- **Net Requirements** — gross requirements minus on-hand inventory and scheduled receipts
- **Planned Orders** — suggested purchase or production orders to cover net requirements
- **Lead Time Offsetting** — orders are planned backward from the need date by the item's lead time

**Capacity Requirements Planning (CRP):** Validates that planned production is feasible:
- Available capacity per work center (hours per period)
- Load from planned and released production orders
- Over/under capacity identification and leveling strategies

### Production Execution

**Production Order (Work Order):** Authorization to manufacture:
- Order number, product, quantity, and due date
- BOM reference and routing (sequence of operations)
- Materials to be consumed (component list with quantities)
- Target work center assignments
- Status: planned → released → in progress → complete → closed

**Routing / Process Plan:** Sequence of manufacturing operations:
- **Operation:** A single step in production (e.g., cutting, welding, assembly, painting, testing)
  - Work center or machine assignment
  - Setup time and run time (per unit)
  - Required tools, fixtures, and programs (CNC programs, etc.)
  - Operator skill requirements
  - Quality checkpoints and in-process inspection requirements

**Shop Floor Control:**
- **Labor Reporting** — operators clock in/out on operations, recording actual time spent
- **Material Consumption** — recording actual materials used (may differ from BOM quantity due to scrap)
- **Output Recording** — reporting completed quantities at each operation
- **Scrap and Rework Reporting** — recording defective units, reason codes, and rework instructions
- **Machine Monitoring** — Overall Equipment Effectiveness (OEE): availability × performance × quality

### Lean Manufacturing Concepts

**Kanban:** Pull-based replenishment system:
- **Kanban Card/Signal:** Triggers production or movement of a specific quantity
- **Kanban Board:** Visual management of work-in-progress
- **Kanban Loop:** Circulating signals between producing and consuming work centers

**Just-in-Time (JIT):** Minimizing inventory by synchronizing supply with demand:
- **Takt Time** — the rate of production needed to match customer demand
- **Continuous Flow** — moving one unit at a time through production steps without batching
- **Heijunka (Level Scheduling)** — smoothing production volume and mix across the planning period

## Warehouse Operations

### Inbound Operations

**Receiving Process:**
1. **Appointment Scheduling** — carriers book dock doors and time slots
2. **Gate Check** — vehicle arrives, driver presents documentation (BOL, packing list)
3. **Unloading** — forklift operators unload pallets or cartons from the vehicle
4. **Receiving Inspection** — quantity verification and quality sampling per inspection plan
5. **Putaway** — system-directed placement to a storage location based on product attributes, velocity, and available space
6. **System Update** — inventory record created/updated, PO receipt confirmed

**Cross-Docking:** Goods received and immediately moved to outbound staging without storage:
- Products pre-allocated to outbound orders
- Minimal handling and near-zero storage time
- Used for time-sensitive, pre-sorted, or high-velocity items

### Outbound Operations

**Order Fulfillment Process:**
1. **Wave Planning** — grouping orders into waves based on carrier pickup times, delivery zones, or priority
2. **Inventory Allocation** — reserving specific inventory for each order (FIFO, FEFO for perishables, or lot-directed)
3. **Pick Path Optimization** — sequencing picks to minimize travel distance (zone picking, batch picking, cluster picking)
4. **Picking** — retrieving items from storage locations:
   - **Single Order Picking** — one picker, one order at a time
   - **Batch Picking** — one picker collects items for multiple orders simultaneously
   - **Zone Picking** — pickers are assigned to zones, orders move between zones
   - **Wave Picking** — combined batch and zone approach, synchronized by wave release
5. **Packing** — items placed in shipping containers with dunnage, packing slips, and labels
6. **Shipping** — cartons/pallets staged at dock doors, manifested with carrier, loaded onto vehicles

### Inventory Accuracy

**Cycle Counting:** Periodic physical counting of a subset of inventory:
- **ABC Cycle Count:** A items counted quarterly, B items semi-annually, C items annually
- **Random Cycle Count:** Random selection of locations counted daily
- **Variance Threshold:** Discrepancies above threshold trigger investigation and adjustment
- **Count Accuracy Target:** >99.5% at the location level

**Physical Inventory:** Complete count of all inventory, typically annually:
- Warehouse operations suspended during count (blind count vs. system-assisted count)
- Multiple count teams with independent recounts for discrepancies
- Adjustment approval process with financial impact review

## Returns and Reverse Logistics

### Returns Management

**Return Merchandise Authorization (RMA):**
- Customer requests return with reason code (defective, wrong item, change of mind, warranty claim)
- RMA number issued with return instructions and shipping label
- Return window validation (within return policy period)

**Returns Processing:**
1. **Receipt** — returned item received and matched to RMA
2. **Inspection** — condition assessment (new, like-new, damaged, defective)
3. **Disposition Decision:**
   - **Restock** — return to available inventory (A-grade condition)
   - **Refurbish** — repair/repackage before restocking (B-grade)
   - **Liquidate** — sell through secondary channels at discount
   - **Recycle** — disassemble and recover materials
   - **Dispose** — scrap with proper waste handling
4. **Credit/Replacement** — issue refund or ship replacement to customer
5. **Root Cause Analysis** — aggregate return reasons by product for quality improvement

## Supply Chain Visibility and Analytics

### Key Performance Indicators (KPIs)

**Supply Chain KPIs** measure end-to-end performance:

| KPI | Definition | Target |
|-----|-----------|--------|
| Perfect Order Rate | Orders delivered in full, on time, damage-free, with correct documentation | >95% |
| Order Cycle Time | Time from order placement to delivery | Varies by channel |
| Inventory Turnover | Cost of goods sold / average inventory value | Industry dependent |
| Days of Supply | On-hand inventory / average daily demand | 15-45 days |
| Fill Rate | Units shipped / units ordered (at line item level) | >98% |
| On-Time In-Full (OTIF) | Orders arriving at customer on the promised date with complete quantity | >95% |
| Cost to Serve | Total supply chain cost per order or per unit | Minimize |
| Cash-to-Cash Cycle | Days inventory outstanding + days sales outstanding - days payable outstanding | Minimize |
| Supplier Lead Time Variability | Standard deviation of actual vs. quoted lead times | Minimize |
| Warehouse Utilization | Used storage capacity / total capacity | 80-90% |

### Supply Chain Risk Management

**Risk Categories:**
- **Supply Risk** — supplier bankruptcy, quality failure, capacity constraint, single-source dependency
- **Demand Risk** — forecast error, demand volatility, bullwhip effect, market shift
- **Logistics Risk** — transportation disruption, port congestion, border delays, carrier insolvency
- **Environmental Risk** — natural disasters, climate events, pandemic, geopolitical instability
- **Cyber Risk** — ransomware attack on supply chain systems, data breach, IoT device compromise

**Risk Mitigation Strategies:**
- **Dual/Multi-Sourcing** — qualifying multiple suppliers for critical materials
- **Safety Stock** — buffer inventory proportional to demand and supply variability
- **Geographic Diversification** — sourcing from multiple regions to avoid concentration risk
- **Business Continuity Plan (BCP)** — documented response procedures for disruption scenarios
- **Supply Chain Control Tower** — real-time visibility platform integrating data from all supply chain partners for proactive risk detection
