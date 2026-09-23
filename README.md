# ReturnFlow

ReturnFlow is a context-aware return request agent. It combines trusted order data, persisted
conversation state, deterministic return policy, and replaceable fact extractors to ask only the
questions that are still necessary.

The supported MVP policies are deliberately narrow: the order must be delivered, the request must
be within 30 days, final-sale items cannot be returned, and used non-defective items are rejected.
Defects, conflicting information, and unsupported cases go to human review.

Implementation and run instructions are added alongside the application in later phases.
