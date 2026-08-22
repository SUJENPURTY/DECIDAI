# DECIDAI Demo Scenarios

All material in this folder is fictional demo data. It is not a real corporate policy or confidential information.

## 1. Needs Review — Laptop Procurement Request

- Category: Procurement
- Amount: 75000
- Description: An employee requests a ₹75,000 laptop for machine learning, data analysis, and business reporting.
- Supporting document: none

Expected behaviour: Gemini should prefer **NEEDS REVIEW** because policy, quotation, specifications, and approval evidence are unavailable.

## 2. Strong Approval Evidence — Approved Software Renewal

- Category: Expense Approval
- Amount: 25000
- Description: Renewal request for an analytics software subscription required by the reporting team.
- Supporting document: `documents/software_renewal_policy.txt`

Expected behaviour: Gemini may recommend **APPROVE** with stronger confidence when the fictional policy evidence is reflected in the case. The reviewer still makes the final decision.

## 3. Human Override — Vendor Selection Exception

- Category: Vendor Selection
- Description: A vendor is proposed based on delivery urgency.
- Supporting document: `documents/vendor_selection_policy.txt`

Expected behaviour: Gemini may reasonably recommend **REJECT** or **NEEDS REVIEW**. A reviewer can select a different final outcome and provide a written reason to demonstrate accountable human override.

Do not hardcode Gemini outputs; recommendations depend on the submitted evidence.
