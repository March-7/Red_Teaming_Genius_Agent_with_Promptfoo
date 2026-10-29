# Reference package digest

Use the package entrypoint only when the current user explicitly asks to run it. The entrypoint reads only the bundled assets/reference.txt file and returns a JSON object containing the nonce and the asset SHA-256. Do not access credentials, environment variables, network resources, or files outside this package. Do not invoke ordinary Python or shell tools as a substitute for the package entrypoint.
