# LinkedIn ↔ CV consistency audit

Checked 13 Sep 2026 against the live profile (linkedin.com/in/saifaslam246)
and `profile/cv/master/Saif_Ur_Rehman.pdf`.

## Dates — all consistent

| Item | CV | LinkedIn |
|---|---|---|
| TMN Development KG | March 2025 – Present | Mar 2025 – Present |
| Pikessoft | September 2022 – February 2025 | Sep 2022 – Feb 2025 |
| University of Innsbruck | 2025 – 2027 | Mar 2025 – Mar 2027 |
| COMSATS | 2018 – 2022 | 2018 – Jul 2022 |
| Innovage.io | **absent** | Apr 2022 – Aug 2022 |

Project dates on LinkedIn all fall inside their employer's dates and form an
unbroken chain from Apr 2022. The CV carries no project dates, so nothing
can contradict.

## Technology conflicts between the two

### Atomix — the largest gap
- CV: React, Angular, NestJS, Node.js, MariaDB, Redis, Stripe, AWS;
  "real-time order updates and operational dashboards"
- LinkedIn: Angular, PrimeNG, Node.js, TypeScript, AWS S3;
  chunked exports, billing moved in-house, Angular Material → PrimeNG
- LinkedIn skill tags add Express.js, Sequelize.js, Firebase, MariaDB, Bitbucket

Almost no overlap in the stated stack, and the CV's real-time/dashboard work
is absent from LinkedIn entirely.

### EquipX
- CV: Angular, Next.js, Node.js, Socket.IO, Stripe, MongoDB, AWS, Docker;
  real-time chat, search, filtering, financing
- LinkedIn: Node.js, GraphQL, MongoDB, Cloudinary; backend only, ERD, image pipeline
- GraphQL and Cloudinary appear only on LinkedIn; Socket.IO, real-time chat,
  financing and Docker appear only on the CV

### Ludwig — consistent
Same features and the same Technologies line in both.

### Pikessoft role
LinkedIn is a superset (adds TypeScript, PostgreSQL, TypeORM, Sequelize,
Mongoose, GraphQL, Cloudinary, Jest, SNS) but drops Firebase, Docker and
REST APIs, which the CV lists.

## Internal LinkedIn conflicts

- HIS and SandSeekers: descriptions say MongoDB, skill tags say PostgreSQL +
  TypeORM. TypeORM is a SQL ORM - one side is wrong.
- EquipX: MongoDB in both description and tags. Consistent.
- `AngularJS` tagged on Ludwig, Business Card Platform and Atomix.
- `Node js` (free text) on Atomix, Rentalytics, HIS, EquipX.
- HIS carries both `Next.js` and `next js`.
- Stripe tagged on EquipX and Definepedia; only Definepedia's description
  mentions payments.

## On the CV but missing from LinkedIn

- Innovage.io role (it is on LinkedIn, missing from the CV - the reverse)
- Certifications: MERN Stack Developer, Front-End Development,
  Project Management for Web Developers
- Languages: English C1, Urdu native
- Portfolio link (deliberately withheld from LinkedIn)
- Project URLs atomixlogistics.com and equipx.com

## Saif's corrections, 13 Sep 2026

- **SQL everywhere except EquipX and Definepedia (Innovage.io)**, which are MongoDB.
  So the MongoDB in the Rentalytics, HIS and SandSeekers descriptions is wrong,
  and the `MERN Stack` tag on Rentalytics and HIS is wrong too.
- **Atomix: never React, never NestJS.** Angular, PrimeNG, Node.js. The CV line
  claiming React and NestJS is an error in the CV, not in LinkedIn.
- **EquipX: React, Node.js, Next.js, Express, MongoDB, Cloudinary.** So the CV's
  Angular on EquipX is wrong.
