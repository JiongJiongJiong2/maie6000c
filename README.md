# MemeRetrieve

English · [简体中文](README.zh-CN.md)

Find the original animated GIF from a screenshot. Upload a cropped PNG, JPEG or WebP to search the reference collection and your private GIF library. If your installation enables online search, you can ask the search agent to look further, watch its progress and save the original. Once a saved GIF is indexed, another frame can find it after a restart, even with external search turned off.

| What do you need? | English | 简体中文 |
| --- | --- | --- |
| Product overview, capabilities, limitations and proposed business model | [Product](docs/product/README.md) | [产品说明](docs/product/README.zh-CN.md) |
| Register, find a GIF, run Docker, rehearse the beta or roll back a release | [User and operator guides](docs/guides/README.md) | [使用与部署指南](docs/guides/README.zh-CN.md) |
| Understand the API, worker, image and animation vectors, storage and tests | [Technical documentation](docs/technical/README.md) | [技术文档](docs/technical/README.zh-CN.md) |

## Try it

For a new installation, follow the [Docker setup](docs/guides/product-deployment.md) and open `http://127.0.0.1:8000/web/` on the host. Choose **Local only**, upload a screenshot and play a result. With online search enabled, **Continue online** starts a linked job and **Confirm and save** adds a result to your private library.

The [invite-only rehearsal](docs/guides/public-beta.md) runs on the operator’s computer at `http://127.0.0.1:58095/web/`. Registration requires the operator’s invite code. That profile uses local retrieval and disables external search and AI annotation.

## What has been verified?

The real browser flow recovered a 44-frame GIF with a source clue, saved it, found it from a different frame after an offline restart and downloaded bytes identical to the original. In the separate beta rehearsal, frames 13 and 29 each ranked the same saved GIF first. Both downloads matched all 1,001,718 bytes. These runs establish the behavior on specific licensed examples. Accuracy on independent user screenshots still needs measurement. [Release evidence](submissions/week13/README.en.md) · [Beta receipt](submissions/week13/public-beta-rehearsal.json)

## Repository map

The browser client lives in [web/](web/), the FastAPI service, worker and retrieval code in [services/](services/), and PostgreSQL migrations in [alembic/](alembic/). [scripts/](scripts/) contains setup and verification commands, [tests/](tests/) contains backend tests, and [GitHub Actions](.github/workflows/) builds and verifies the application and release containers. The [documentation index](docs/README.md) also maps earlier experiments, source-specific notes, course submissions and templates.

## Historical W04 proposal context

Memeory began with a proposal for one iPhone user searching a curated GIF collection. The Week 4 architecture, Week 7 demo and Week 13 delivery record how that scope developed into the account-based web application. [Week 4 proposal](submissions/week04/README.md) · [Week 7 demo](submissions/week07/README.md) · [Week 13 delivery](submissions/week13/README.en.md) · [Previous repository introduction](https://github.com/JiongJiongJiong2/maie6000c/blob/03ddad76dda3d63ed95f58e6993ae97830a1d86b/README.md)
