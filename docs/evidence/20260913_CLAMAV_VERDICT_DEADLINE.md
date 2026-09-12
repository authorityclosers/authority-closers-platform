# ClamAV verdict deadline correction

The INSTREAM sender previously reused its 15-second chunk I/O timeout while
waiting for ClamAV to finish scanning. A large admitted video could therefore
fail after upload even though the configured total scan deadline had time left.

The response now has an independent 1,200-second budget capped by the absolute
scan deadline. Fragmented replies cannot extend that budget. Chunk writes keep
their shorter timeout, and a clean verdict still requires the exact response,
connection EOF, unchanged source metadata and matching checksum.

Validation: 97 scanner tests passed, including a real loopback protocol peer
whose delayed verdict exceeds the chunk timeout, plus existing deadline,
malware, engine-limit, metadata and fragmented-response checks. Ruff passed for
the implementation and scanner tests. This is transport regression evidence;
it is not a production daemon scan or a near-limit performance acceptance.
