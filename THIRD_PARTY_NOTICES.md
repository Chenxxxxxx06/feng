# Third-Party Notices

This project uses the following third-party open source software.

## Backend (Python)

| Package | License | Usage |
|---------|---------|-------|
| FastAPI | MIT | Web framework |
| SQLAlchemy | MIT | ORM / database |
| Alembic | MIT | Database migrations |
| Pydantic | MIT | Data validation |
| httpx | BSD | HTTP client |
| pytest | MIT | Testing |
| pytest-asyncio | Apache 2.0 | Async test support |
| numpy | BSD-3 | Numerical computing |
| scipy | BSD-3 | Scientific computing |
| scikit-learn | BSD-3 | Machine learning |
| networkx | BSD-3 | Graph algorithms |
| opencv-python | Apache 2.0 | Image processing |
| Pillow | MIT-CMU | Image processing |
| python-jose | MIT | JWT handling |
| passlib | BSD | Password hashing |
| python-multipart | Apache 2.0 | File uploads |
| PyYAML | MIT | YAML parsing |
| python-dotenv | BSD | Environment config |
| uvicorn | BSD | ASGI server |
| openpyxl | MIT | Excel file handling |
| reportlab | BSD | PDF generation |

## Frontend (TypeScript/JavaScript)

| Package | License | Usage |
|---------|---------|-------|
| React | MIT | UI framework |
| TypeScript | Apache 2.0 | Type system |
| Vite | MIT | Build tool |
| Tailwind CSS | MIT | CSS framework |
| ECharts | Apache 2.0 | Charts / visualization |
| Three.js | MIT | 3D rendering |
| Playwright | Apache 2.0 | E2E testing |
| Zustand | MIT | State management |
| React Router | MIT | Routing |
| Axios | MIT | HTTP client |

## Data Sources

| Dataset | License | Source |
|---------|---------|--------|
| CARE to Compare v6 | CC BY-SA 4.0 | Fraunhofer IEE / Zenodo |
| DTU Wind Energy | CC BY-NC 3.0 | DTU Data |
| ERA5 | Copernicus License | ECMWF / CDS |

**Note**: Datasets marked CC BY-NC or with non-commercial restrictions are NOT redistributed
in this repository. Only download scripts, source references, and checksums are included.
See `data/README.md` for dataset inventory and access instructions.

## AI Models

| Model | Provider | Access |
|-------|----------|--------|
| Qwen3.7-Max | Alibaba Cloud (DashScope) | API — requires key |
| Qwen-Plus | Alibaba Cloud (DashScope) | API — requires key |
| YOLOv8 | Ultralytics (AGPL-3.0) | Local inference |

LLM API access requires a DashScope API key. The project degrades gracefully
when the key is unavailable (rule-based fallbacks for diagnosis, static plans for decisions).

## License of This Project

Code: Apache License 2.0 (see [LICENSE](../LICENSE))
Data: See individual dataset licenses above. Data files are NOT redistributed.
Documentation: CC BY 4.0
Models: See model-specific licenses above.
