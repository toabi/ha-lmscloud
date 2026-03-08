# LMS Cloud

Home Assistant integration for LMSCloud Accounts. LMSCloud is a service which hosts and services
KOHA for public libraries. Koha is a fully featured, scalable library management system.

## Prerequisites

- An account of a library which uses LMSCloud

## Installation

### Via HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Install "LMSCloud" from HACS
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

### Manual

1. Copy the `custom_components/lmscloud` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services

## Features

Once configured, this integration allows you to access data from your library account from Home Assistant.

Current MVP features:

- Add your LMSCloud account using `base_domain`, `username`, and `password`
- Optional timezone setting for parsing local OPAC dates (defaults to your Home Assistant timezone)
- Sensors for:
  - currently borrowed books (with per-item details)
  - overdue books
  - next due date
  - next extension possible (with per-item details)
  - holds ready for pickup
  - fees balance

## Authentication notes:

- Uses the Koha OPAC cookie-based login flow (`/cgi-bin/koha/opac-user.pl`)
- This is useful for LMSCloud instances where API Basic authentication is disabled
- Account values are scraped from OPAC pages (`opac-user.pl` and `opac-account.pl`)
