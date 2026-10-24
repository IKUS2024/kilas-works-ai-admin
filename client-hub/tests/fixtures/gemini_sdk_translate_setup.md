# Official SDK wire fixture

Generated offline on2026-10-24 using google-genai2.33.0:
`_LiveConnectParameters_to_mldev(client._api_client, parameters.model_dump(exclude_none=True))`.
Removed the converter's empty `config` object as the SDK does before sending.
Client used a synthetic dummy key; socket.connect was patched to reject network.
No provider call or new application dependency.

Parameters: model gemini-3.5-live-translate-preview, AUDIO response, input/output
transcription enabled, target id, echo_target_language=false.
SDK GenerationConfig rejects inputAudioTranscription/outputAudioTranscription
with extra_forbidden. Those fields belong directly under setup. The translation
config itself remains inside generationConfig. The raw translation guide example
conflicts with this; the API schema and SDK serialization agree.

Sources:
https://github.com/googleapis/python-genai/blob/main/google/genai/_live_converters.py
https://ai.google.dev/api/live#bidigeneratecontentsetup
https://ai.google.dev/gemini-api/docs/live-api/live-translate
