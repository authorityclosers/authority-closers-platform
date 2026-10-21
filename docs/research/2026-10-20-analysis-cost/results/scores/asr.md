| arm | variant | calls | CER | tCER | tWER | critical kept | speaker acc | tCER by language |
|---|---|---:|---:|---:|---:|---:|---:|---|
| assemblyai_universal-2 | clean_16k | 2 | 24.8% | 23.3% | 50.0% | 0.0% | 100.0% | {'hi': 0.052, 'mr': 0.39} |
| assemblyai_universal-2 | phone_8k | 18 | 38.7% | 26.8% | 47.5% | 28.3% | 94.2% | {'en-IN': 0.066, 'hi': 0.176, 'hi-en': 0.227, 'mr': 0.574, 'mr-en': 0.427} |
| assemblyai_universal-3-5-pro | phone_8k | 16 | 34.7% | 22.1% | 42.2% | 45.5% | 93.2% | {'en-IN': 0.077, 'hi': 0.178, 'hi-en': 0.261, 'mr-en': 0.273} |
| deepgram_nova-3 | clean_16k | 2 | 37.8% | 24.9% | 58.3% | 0.0% | 96.6% | {'hi': 0.156, 'mr': 0.329} |
| deepgram_nova-3 | phone_8k | 18 | 31.6% | 25.4% | 42.6% | 50.4% | 79.0% | {'en-IN': 0.067, 'hi': 0.2, 'hi-en': 0.05, 'mr': 0.963, 'mr-en': 0.387} |
| groq_whisper-large-v3 | clean_16k | 2 | 47.2% | 41.5% | 72.6% | 0.0% | 65.8% | {'hi': 0.368, 'mr': 0.456} |
| groq_whisper-large-v3 | phone_8k | 16 | 34.3% | 25.6% | 40.8% | 37.5% | 50.4% | {'en-IN': 0.07, 'hi': 0.253, 'hi-en': 0.247, 'mr': 0.599, 'mr-en': 0.408} |
| groq_whisper-large-v3-turbo | clean_16k | 2 | 34.2% | 32.3% | 67.6% | 0.0% | 65.8% | {'hi': 0.176, 'mr': 0.451} |
| groq_whisper-large-v3-turbo | phone_8k | 16 | 37.7% | 28.2% | 44.7% | 37.4% | 52.2% | {'en-IN': 0.071, 'hi': 0.317, 'hi-en': 0.294, 'mr': 0.573, 'mr-en': 0.404} |
| local_faster-whisper-large-v3 | phone_8k | 15 | 31.8% | 21.7% | 35.5% | 40.0% | 51.7% | {'en-IN': 0.07, 'hi': 0.221, 'hi-en': 0.202, 'mr': 0.714, 'mr-en': 0.266} |
| local_faster-whisper-large-v3-turbo | phone_8k | 15 | 36.1% | 25.6% | 39.4% | 38.7% | 52.3% | {'en-IN': 0.07, 'hi': 0.265, 'hi-en': 0.226, 'mr': 0.825, 'mr-en': 0.296} |
| openrouter_google_gemini-3.1-flash-lite | clean_16k | 2 | 3.3% | 3.4% | 14.0% | 0.0% | 89.2% | {'hi': 0.025, 'mr': 0.042} |
| openrouter_google_gemini-3.1-flash-lite | phone_8k | 18 | 33.6% | 17.2% | 28.3% | 42.3% | 73.8% | {'en-IN': 0.06, 'hi': 0.241, 'hi-en': 0.2, 'mr': 0.26, 'mr-en': 0.129} |
| openrouter_google_gemini-3.5-flash-lite | phone_8k | 16 | 68.5% | 35.1% | 52.5% | 33.3% | 71.9% | {'en-IN': 0.066, 'hi': 0.373, 'hi-en': 0.177, 'mr-en': 0.438} |
| openrouter_google_gemini-3.8-flash | phone_8k | 14 | 13.4% | 8.3% | 12.2% | 51.2% | 99.2% | {'en-IN': 0.062, 'hi': 0.102, 'hi-en': 0.139, 'mr-en': 0.123} |
| sarvam_saaras-v4 | clean_16k | 2 | 3.6% | 4.0% | 13.1% | 0.0% | 85.2% | {'hi': 0.031, 'mr': 0.047} |
| sarvam_saaras-v4 | phone_8k | 13+5 failed | 23.0% | 12.6% | 22.8% | 45.8% | 92.6% | {'en-IN': 0.072, 'hi': 0.111, 'hi-en': 0.204, 'mr': 0.256, 'mr-en': 0.122} |
