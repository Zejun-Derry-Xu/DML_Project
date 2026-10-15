# Apparel facts v2.0.0 — catalog category is authoritative

stained: true only for explicit stains; false only explicit no stains/clean; otherwise null.
tags_attached: whether original tags remain physically fastened. 'Tags still attached' -> true.
tags_intact: whether tags are undamaged. Attached does NOT imply intact; removed does NOT imply torn.
damaged: clothing itself is damaged. 'Tags are damaged' affects tags_intact, not damaged.
condition_origin: customer only if customer explicitly caused the adverse condition;
pre_existing only if present on arrival/delivery; unknown if explicitly unsure of the cause;
null if the cause was not mentioned. Never infer fault from a missing tag.
Neither unused nor worn implies clean/undamaged/attached tags/intact tags.
Wearing is NOT a rejection or a return reason. Eligibility belongs to the policy engine.
During a focused question extract other EXPLICIT apparel condition facts as well.

Examples (all other facts remain null/default):
- 'The tags are still attached.' -> tags_attached=true; tags_intact=null
- 'I cut off the tags.' -> tags_attached=false, condition_origin=customer
- 'It arrived with a stain.' -> stained=true, condition_origin=pre_existing
- 'The tags are missing; I do not know who removed them.' -> tags_attached=false, condition_origin=unknown
- 'I never wore it.' -> used=false, stained=null, damaged=null, tags_attached=null, tags_intact=null
- 'The shirt is too small.' -> reason=does_not_fit, damaged=null
- 'The tags are torn.' -> tags_intact=false, damaged=null, condition_origin=null
