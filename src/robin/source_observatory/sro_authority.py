"""Reviewed trust anchors outside the mutable packet, avoiding recursive pins.

Updating these values is a source change requiring independent Council keys;
an execution packet cannot grant itself a new authority.
"""

APPROVED_PLAN_SHA256 = "acde2eaa58c9da8f1c853a1aab9f77c02a835ec1c1005addf5404e8eb21fbf94"
APPROVED_MANIFEST_SHA256 = "2f5aa15d050f4a7c0f5f52a0e1f1be0288f664277b1555a7f6e67c7b7433b2e0"
APPROVED_E1_SHA256 = "390e173605d7e30251238f350e13f241a0a15f46c997899622f3025df061aa6a"
