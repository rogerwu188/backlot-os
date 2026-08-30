# Hell Grind Western Martial Action Reference

This is an opt-in task2-1 prompt-rule adapter, not a model-weight package. It
contains derived direction rules only; it does not ship raw source prompts,
source media, or Seedance/video-model weights.

Use it only with the `AMERICAN_HOLLYWOOD` profile:

```json
{
  "task2_1_reference_library": {
    "library_id": "HELL_GRIND_WESTERN_MARTIAL_ACTION_REFERENCE_V1",
    "profile_id": "AMERICAN_HOLLYWOOD",
    "expected_sha256": "f04e1b2f95cb8f7511022723e690bfcb4d29b00dc6fa0e9ace9cca38dc7bdbf9"
  }
}
```

The compiler rejects an absent or mismatched SHA, any non-American-Hollywood
profile, and any library that embeds raw source prompts or model weights. Its
manifest records the library and rule-set SHA as the task2-1 Stage-E binding.
