# Supply Chain Management Domain Model

## Overview

A supply chain encompasses the entire lifecycle of a product from raw material sourcing through manufacturing, distribution, and delivery to the end customer. This document defines the core entities, relationships, and structures in a modern supply chain management system including procurement, manufacturing, logistics, warehousing, and quality management.

## Organizations and Partners

A **Supply Chain Partner** is any organization participating in the supply chain network. Each partner has a partner ID, legal name, trading name, registration number, headquarters address, and operational countries.

### Partner Types

**Supplier:** Provides raw materials, components, or services. Characterized by:
- Supplier rating (1-5 stars based on quality, delivery, and cost performance)
- Lead time (days from order to delivery) — standard and expedited
- Minimum order quantity (MOQ) and economic order quantity (EOQ)
- Payment terms (Net 30, Net 60, 2/10 Net 30)
- Geographic location and operational regions
- Certifications held (ISO 9001, ISO 14001, SA 8000, Fair Trade)
- Capacity utilization and surge capacity
- Supplier tier classification: Tier 1 (direct), Tier 2 (sub-supplier), Tier 3 (raw material source)
- Periodic quality audit results and corrective action history

**Manufacturer:** Transforms raw materials and components into finished goods. Has:
- Production capacity (units per day/week/month) by product line
- Manufacturing processes: discrete, process, batch, continuous flow, make-to-order, make-to-stock
- Factory locations with address, timezone, and local regulations
- Quality certifications: ISO 9001, IATF 16949 (automotive), AS9100 (aerospace), GMP (pharmaceutical)
- Production lines with current product assignments and changeover times
- Bill of materials (BOM) management and version control
- Work-in-progress (WIP) tracking at each production stage

**Contract Manufacturer (CMO):** A manufacturer that produces goods under another company's brand. Additional attributes:
- Non-disclosure agreement (NDA) reference
- Intellectual property (IP) ownership terms
- Minimum production run size
- Quality inspection rights and audit frequency

**Distributor:** An intermediary that purchases products from manufacturers and sells to retailers or other distributors. Operates:
- One or more warehouses and distribution centers
- Transportation fleet or third-party logistics contracts
- Territory agreements defining geographic exclusivity
- Value-added services: kitting, labeling, packaging, light assembly

**Retailer:** Sells products to end consumers. Channels include:
- Physical stores with store ID, location, size (sq ft), and format (flagship, standard, outlet, kiosk)
- E-commerce platform with URL, marketplace integration (Amazon, eBay, Shopify)
- Omnichannel fulfillment capabilities: ship-from-store, buy-online-pick-up-in-store (BOPIS), curbside pickup

**Logistics Provider (3PL/4PL):** Handles transportation, warehousing, and fulfillment services:
- Service types: full truckload (FTL), less-than-truckload (LTL), parcel, intermodal, air freight, ocean freight, rail
- Network coverage: domestic, regional, international
- Technology platform: TMS (transportation management system), WMS (warehouse management system)
- SLA terms: transit time guarantees, damage rates, on-time delivery percentage
- Carrier partners and rate contracts

## Products and Materials

### Product Hierarchy

A **Product** is any item tracked in the supply chain. Products form a hierarchy:

**Raw Material:** A basic input to manufacturing that undergoes transformation. Examples: steel coils, cotton bales, silicon wafers, petroleum, wood pulp. Attributes:
- Material grade and specification (e.g., ASTM A36 steel, 100% long-staple cotton)
- Source region and country of origin
- Hazardous material classification (HAZMAT class, UN number if applicable)
- Shelf life and storage requirements (temperature, humidity, light sensitivity)
- Unit of measure: kg, liter, meter, ton, barrel
- Market price index reference for commodity materials

**Component:** An intermediate item assembled from raw materials and/or other components. Examples: circuit boards, engine blocks, fabric panels, pharmaceutical intermediates. Attributes:
- Engineering drawing reference and revision number
- Bill of materials (component BOM — recursive structure)
- Critical-to-quality (CTQ) characteristics with tolerance specifications
- Interchangeability: can this component be substituted with an alternative?
- Make/buy decision and preferred sourcing strategy

**Sub-Assembly:** A partially assembled product composed of multiple components. Attributes:
- Assembly instructions and work instruction document
- Test procedures at this stage
- Station/cell where assembly occurs

**Finished Good:** A product ready for sale to end customers. Attributes:
- SKU (Stock Keeping Unit) and UPC/EAN barcode
- MSRP (manufacturer's suggested retail price) and wholesale price
- Weight, dimensions, and shipping class
- Warranty period and warranty terms
- Category and subcategory in the product catalog
- Product lifecycle stage: introduction, growth, maturity, decline, end-of-life
- Regulatory approvals: FDA (food/drug), CE (European conformity), FCC (electronics), UL (safety)

**Service Part / Spare Part:** A component sold separately for maintenance and repair. Has:
- Interchangeability group (which products this part fits)
- Supersession chain (which older part numbers this replaces)
- Criticality classification: mission-critical, essential, non-essential

### Bill of Materials (BOM)

A **Bill of Materials** defines the hierarchical composition of a product:
- **BOM Header:** product being assembled, BOM version, effective date, engineering change notice (ECN) reference
- **BOM Line Item:** component or material used, quantity required, unit of measure, position/reference designator, scrap factor (expected waste %)
- **BOM Levels:** a multi-level BOM explodes the full material tree; a single-level BOM shows only direct children
- **Phantom BOM:** a sub-assembly that exists logically but is not stocked — consumed immediately in production

### Product Configuration

For configurable products (e.g., laptops, vehicles), a **Product Configurator** defines:
- **Configuration Options:** the available choices (color, size, material, features)
- **Configuration Rules:** constraints on valid combinations (this engine requires that transmission)
- **Configuration BOM:** the BOM is dynamically generated based on selected options

## Inventory and Warehousing

### Warehouse Structure

A **Warehouse** (or Distribution Center) is a physical facility for storing and handling goods:
- Warehouse ID, name, and type (raw material, finished goods, cold chain, bonded, cross-dock)
- Physical address, GPS coordinates, and timezone
- Total capacity (cubic meters or pallet positions) and current utilization %
- Operating hours and shifts
- Fire safety rating and security level

**Storage Zones** divide a warehouse into functional areas:
- **Receiving Zone** — where inbound goods are unloaded and inspected
- **Bulk Storage** — high-density racking for full pallets (selective, drive-in, push-back, pallet flow)
- **Pick Zone** — shelving or carton flow for order picking
- **Cold Storage** — temperature-controlled area (frozen: <-18°C, chilled: 2-8°C)
- **Hazmat Zone** — isolated area for hazardous materials with special ventilation and containment
- **Staging Area** — where outbound orders are assembled before loading
- **Returns Processing** — area for inspecting and dispositioning returned goods

**Storage Locations** provide granular addressing:
- Aisle, rack, level, position (e.g., A-03-2-B means Aisle A, Rack 3, Level 2, Position B)
- Location type: pallet, shelf, bin, floor, hanging
- Weight capacity and dimension constraints
- Assignment rules: fixed location, random/chaotic, zone-based

### Inventory Management

An **Inventory Record** tracks the quantity and status of a product at a location:
- Product reference and location reference
- Quantity on hand, quantity reserved (for open orders), quantity available
- Lot number and batch number (for traceability)
- Serial numbers (for serialized items)
- Expiration date and best-before date (for perishables and pharmaceuticals)
- Received date and days in inventory (age)
- Inventory status: available, quarantined (pending inspection), damaged, on hold, in transit

**Stock Movements** record every inventory change:
- **Goods Receipt** — inbound from supplier, transfer, or production
- **Goods Issue** — outbound for orders, production consumption, or disposal
- **Stock Transfer** — movement between locations within a warehouse or between warehouses
- **Cycle Count Adjustment** — correction after physical count
- **Scrap/Write-Off** — removal of damaged or obsolete inventory

**Inventory Policies** govern replenishment:
- **Reorder Point (ROP)** — minimum quantity that triggers a replenishment order
- **Safety Stock** — buffer quantity to protect against demand variability and supply disruptions
- **Economic Order Quantity (EOQ)** — optimal order quantity minimizing total cost (ordering + holding)
- **ABC Classification** — categorization by value: A items (top 20% by value, tight control), B items (middle, moderate control), C items (bottom, minimal control)

## Orders and Procurement

### Purchase Orders

A **Purchase Order (PO)** is a formal request from a buyer to a supplier:
- PO number, issue date, and requested delivery date
- Buyer information and ship-to address
- Supplier information
- Payment terms and Incoterms (EXW, FOB, CIF, DDP, etc.)
- PO status lifecycle: draft → approved → sent → acknowledged → partially received → fully received → closed → cancelled
- Currency and exchange rate (for international POs)

**PO Line Items** detail what is being ordered:
- Product/material reference, description, and unit of measure
- Quantity ordered, quantity received, and quantity outstanding
- Unit price and total line amount
- Tax code and tax amount
- Requested delivery date (may differ per line)
- Quality inspection requirements

### Sales Orders

A **Sales Order** captures customer demand:
- Order number, order date, customer reference (customer PO number)
- Customer information, billing address, and shipping address
- Shipping method and requested delivery date
- Order priority: standard, expedited, rush
- Order status: received → confirmed → allocated → picked → packed → shipped → delivered → invoiced → closed
- Payment method and payment status

**Order Line Items:**
- Product SKU, description, quantity ordered
- Unit price, discounts, and total line amount
- Promised delivery date and actual ship date
- Fulfillment location (which warehouse ships this line)
- Backorder flag and expected availability date

### Demand Planning

**Demand Forecast:** Predicted future demand for products:
- Forecast period (weekly, monthly, quarterly)
- Forecast method: statistical (moving average, exponential smoothing, ARIMA), causal (regression on drivers), judgment-based
- Forecast accuracy: MAPE (mean absolute percentage error), bias
- Forecast by product, location, customer segment, and channel
- Consensus forecast (blending statistical and sales team inputs)

## Logistics and Transportation

### Shipments

A **Shipment** represents the physical movement of goods:
- Shipment ID and tracking number(s)
- Origin facility and destination (address or facility)
- Carrier and service level (standard, expedited, next-day)
- Shipment mode: FTL, LTL, parcel, air freight, ocean container (FCL/LCL), rail
- Estimated departure date, actual departure date
- Estimated arrival date, actual arrival date
- Proof of delivery (POD) with signature, timestamp, and photo
- Freight cost and billing reference

**Packages / Handling Units:**
Each shipment contains one or more handling units:
- Package type: pallet, carton, crate, drum, envelope
- Weight (gross and tare) and dimensions
- Contents description and item count
- Hazardous goods declaration if applicable
- Labels: shipping label, customs label, handling instructions (fragile, this side up, keep frozen)

### Transportation Management

**Route:** A planned path for a vehicle or shipment:
- Origin, destination, and intermediate stops
- Distance, estimated transit time, and route optimization criteria (cost, time, emissions)

**Carrier Contract:** Agreement between the shipper and carrier:
- Contracted lanes (origin-destination pairs)
- Rate structure: per mile, per hundredweight, per pallet, flat rate
- Volume commitments and discount tiers
- Accessorial charges: liftgate, residential delivery, inside delivery, appointment scheduling
- Claims process and liability limits

**Fleet Vehicle:** Company-owned or leased transportation assets:
- Vehicle type: van, truck (box, flatbed, refrigerated), trailer, container
- Capacity: weight limit and volume limit
- Current location (GPS tracked) and current assignment
- Maintenance schedule and inspection history
- Driver assignment and hours-of-service (HOS) compliance

## Quality Management

### Quality Control

**Quality Inspection:** Evaluation of materials or products against specifications:
- Inspection type: receiving (incoming), in-process, final (outgoing), returned goods
- Inspection plan: what characteristics to check, sampling plan (100%, AQL-based, skip-lot)
- Inspector ID and inspection date/time
- Result: accept, reject, accept-on-concession (with deviation approval)
- Measurement data for each inspected characteristic (actual vs. specification with tolerances)

**Defect:** A recorded quality issue:
- Defect type: dimensional, cosmetic, functional, material, labeling
- Severity: critical (safety hazard), major (affects function), minor (cosmetic)
- Root cause category: supplier quality, machine malfunction, operator error, design flaw, environmental
- Containment action: quarantine affected stock, sort and rework, scrap
- Corrective action (CAPA): short-term fix and long-term prevention
- Cost of quality: scrap cost, rework cost, warranty cost, recall cost

**Non-Conformance Report (NCR):** Formal documentation of a quality deviation:
- Description of the non-conformance
- Disposition: use-as-is, rework, return to supplier, scrap
- Approval authority for the disposition decision
- Impact assessment on downstream processes and customer orders

### Quality Certifications and Standards

**Compliance Certificate:** Attestation that a product or facility meets standards:
- Standard reference (e.g., ISO 9001:2015, FDA 21 CFR Part 820, REACH, RoHS)
- Certifying body and auditor
- Issue date, expiration date, and scope
- Certificate status: active, expired, suspended, revoked

**Test Report:** Documentation of testing performed on a product lot:
- Test methods and equipment used
- Test results with pass/fail determination
- Certificate of Analysis (CoA) for raw materials

## Sustainability and Traceability

**Carbon Footprint Record:** Environmental impact tracking:
- Scope 1 emissions (direct: manufacturing, company vehicles)
- Scope 2 emissions (indirect: purchased electricity, heating)
- Scope 3 emissions (value chain: supplier manufacturing, transportation, product use, end-of-life)
- Carbon intensity per unit of product

**Traceability Record:** Chain of custody from origin to consumer:
- Lot genealogy: which input lots produced which output lots
- Location history: every facility the product passed through
- Temperature log: for cold chain products, continuous temperature monitoring
- Blockchain anchor: hash of traceability data recorded on a distributed ledger for tamper-proof audit trail

**Circular Economy Entities:**
- **Recycled Content:** Percentage of post-consumer or post-industrial recycled material in a product
- **Take-Back Program:** Product return and recycling scheme with collection points, refurbishment processes, and material recovery rates
- **Product Passport:** Digital record of a product's composition, repairability score, and recycling instructions (aligned with EU Digital Product Passport regulation)

## Relationships Summary

- A Supplier **provides** Raw Materials and Components to a Manufacturer
- A Manufacturer **produces** Finished Goods **using** a Bill of Materials
- A BOM **consists of** BOM Line Items, each referencing a Component or Raw Material
- A Sub-Assembly **is composed of** Components (as defined by its BOM)
- A Finished Good **is composed of** Sub-Assemblies and Components
- A Purchase Order **is placed with** a Supplier **by** a Manufacturer or Distributor
- A PO Line Item **references** a Product/Material
- A Warehouse **contains** Storage Zones **containing** Storage Locations
- An Inventory Record **tracks** a Product **at** a Storage Location
- A Stock Movement **changes** an Inventory Record
- A Sales Order **is placed by** a Retailer or Customer
- A Shipment **fulfills** one or more Sales Orders
- A Shipment **is transported by** a Logistics Provider or Fleet Vehicle
- A Shipment **follows** a Route
- A Quality Inspection **is performed on** Products, Raw Materials, or Components
- A Defect **is found during** a Quality Inspection and **affects** a specific Product lot
- A Non-Conformance Report **documents** a Defect and its Disposition
- A Compliance Certificate **is issued for** a Product or Facility
- A Demand Forecast **predicts** future orders for a Product at a Location
- A Carbon Footprint Record **measures** environmental impact of a Product or Shipment
- A Traceability Record **links** Lots through the supply chain from origin to delivery
- A Product Configurator **generates** Configuration BOMs from Configuration Options
