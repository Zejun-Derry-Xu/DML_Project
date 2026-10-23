Clothing fields are independent; wearing does NOT decide eligibility.
stained: explicit stain=true; explicit no stains=false.
damaged: damage to the CLOTHING, not tags/packaging. Explicit no damage=false.
tags_attached: physically fastened=true; removed/missing/no longer attached=false.
tags_intact: undamaged=true; torn/damaged=false. Attached alone does not imply intact.
condition_origin: customer explicitly caused it=customer; present on delivery=pre_existing;
explicitly unsure who caused it=unknown; no stated cause=null.
Never infer good conditions from unused, nor fault from missing tags.
Examples: 'The tags on the shirt are torn' -> tags_intact=false, damaged remains absent.
'There is no damage to the shirt' -> damaged=false, says nothing about tag integrity.
'Tags are attached but damaged' -> tags_attached=true, tags_intact=false.
'It is stained; I don't know who caused it' -> stained=true, condition_origin=unknown.
