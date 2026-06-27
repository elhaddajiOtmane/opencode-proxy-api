# AGENTS.md — Kiro Agent Proxy

> This file is the authoritative context document for any AI agent (Opencode, Antigravity, Gemini CLI, etc.)
> working inside this repository. Read this first before touching any code.

---

## 🎯 What This Project Does

**Kiro Agent Proxy** is a local Python server that acts as a translation layer between AI coding editors
(like [Opencode](https://opencode.ai)) and Amazon's **Kiro** AI backend.

The problem it solves:
- Kiro's backend uses **AWS Binary Event Streams** — a proprietary binary protocol and not sure u need to nvstgate and kitri install heere C:\Users\adam\AppData\Local\Programs\Kiro and    that my cookie session 
kiro-visitor-id=1780634030271-lkeuu8luz;s_fid=0119C9D5EA2E3FDE-12F2E20910AD2E6E;awsccc=eyJlIjoxLCJwIjoxLCJmIjoxLCJhIjoxLCJpIjoiZWU1MmE5YzctMjYzNy00OWI2LThkOWYtMzFmMmYwNTM1MTY1IiwidiI6IjEifQ==;s_sq=%5B%5BB%5D%5D;AccessToken=aoaAAAAAGo_BWwZiOOraI5H1-xuNLS7lfNu-5W1b54Qv-Rm_6fdJgNZB9fADzK89COzxxXF20qsZiH7qRmXZluucoCkc0:MGYCMQDJ09h45ja2YKZ75eL3kCJPExN2Xy6NZJe2/XwZXC/5asEvXrn6vIeUJioR6eN5p9QCMQDJY7QW7iMXsdxZCwql868JQ67I6+6g2DxzLHw85J7TePufgtQKMNotd0iCi1G7q/Q;Idp=Google;RefreshToken=aorAAAAAGq1nlsBdFsSfbRM7nrOAdMQ4taRh8H2HYJkIXFFhwjVX3l2oaRtgHRlqj8b1_qu9tyQLoMf1Hnynnu8hECkc0:MGYCMQCeTtN3dxrnmvK/j0CEROBtJyuE7KdTNc1zvQGLCZn12II4LbZ1pEpw4c/09yIWtkECMQDhfRDZySs78slfDcsVXhhPPIo6vQmMuZn4p0jwts78fdr9n6Q+DWIuywMFHKeq6tg;s_cc=true;UserId=d-9067c98495.24d82488-6071-708e-235c-6be40e2dc241 


.
- AI editors like Opencode expect the **standard OpenAI or antropic `/v1/chat/completions` API**.
- These two formats are completely incompatible — you can't point an editor at Kiro directly.

The proxy sits in the middle and translates in real time:
