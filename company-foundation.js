/* Curated company coverage is independent of robot-owned data/players.json. */
(function () {
  'use strict';
  const checked = '2026-10-18';
  const records = [
    { id: 'transimpact', n: 'TransImpact', site: 'transimpact.com', hq: 'Emerald Isle, NC, USA', address: '8921 Crew Drive, Emerald Isle, NC 28594', al: ['Transportation Impact'], s: 'Parcel spend management provider offering shipping analytics and expert-led carrier contract negotiation, alongside inventory and supply-chain planning.', srcs: ['https://transimpact.com/parcel-spend-management/', 'https://transimpact.com/contact-us/'] },
    { id: 'shipware', n: 'Shipware', site: 'shipware.com', hq: 'San Diego, CA, USA', address: '10815 Rancho Bernardo Rd, Suite 200, San Diego, CA 92127', al: [], s: 'Shipping spend consultancy offering parcel invoice audits, refund recovery and carrier contract optimization for shippers.', srcs: ['https://shipware.com/solutions/invoice-audit-recovery/', 'https://shipware.com/contact/'] },
    { id: 'reveel', n: 'Reveel', site: 'reveelgroup.com', hq: 'Irvine, CA, USA', address: '4521 Campus Dr., Suite 400, Irvine, CA 92612', al: ['Reveel Group'], s: 'Shipping intelligence platform helping shippers understand costs, service performance and carrier relationships.', srcs: ['https://reveelgroup.com/company/', 'https://reveelgroup.com/contact/'] },
    { id: 'sifted', n: 'Sifted', site: 'sifted.com', hq: null, al: [], s: 'Parcel intelligence and auditing provider reviewing invoices, contracts, surcharges, dimensional weight and carrier performance, with refund recovery and claims services.', srcs: ['https://sifted.com/siftedai-parcel-audit/'] },
    { id: 'ljmgroup', n: 'LJM Group', site: 'myljm.com', hq: 'Farmingdale, NY, USA', address: '312 Conklin Street, Farmingdale, NY 11735', al: ['LJM'], s: 'Parcel invoice auditing and recovery consultancy reviewing carrier invoice line items for billing discrepancies.', srcs: ['https://www.myljm.com/services/parcel-invoice-audits', 'https://www.myljm.com/contact-us'] },
    { id: 'shipmatrix', n: 'ShipMatrix', site: 'shipmatrix.com', hq: 'Warrendale, PA, USA', address: '181 Thorn Hill Road, Suite 100, Warrendale, PA 15086', yr: '2000', al: [], s: 'Shipping technology and analytics provider using carrier data to help shippers reduce parcel costs and improve service performance.', srcs: ['https://shipmatrix.com/about-us/'] },
    { id: 'lojistic', n: 'Lojistic', site: 'lojistic.com', hq: null, al: [], s: 'Shipping spend management platform providing analytics, contract intelligence, invoice management and audit and refund recovery across carriers and shipping modes.', srcs: ['https://www.lojistic.com/'] },
    { id: 'intelligentaudit', n: 'Intelligent Audit', site: 'intelligentaudit.com', hq: 'Rochelle Park, NJ, USA', address: '365 West Passaic Street, 4th Floor, Rochelle Park, NJ 07662', al: [], s: 'Transportation audit and analytics provider offering parcel audit and recovery, shipping spend management and carrier payment services.', srcs: ['https://www.intelligentaudit.com/faq', 'https://www.intelligentaudit.com/'] },
  ].map(p => ({ own: null, parent: null, tk: null, yr: null, ...p, realm: 'consultancy', src: p.srcs[0], chk: checked, foundation: true, vet: 'Services checked against company sources. Ownership and transaction history have not been verified. Listed addresses are company-published contact locations; no geographic position is inferred.' }));
  const identity = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  function merge(players) {
    records.forEach(record => {
      const names = [record.n, ...record.al].map(identity);
      const existing = players.find(p => p.id === record.id || [p.n, ...(p.al || [])].some(n => names.includes(identity(n))));
      if (existing) {
        // Preserve canonical identity, established ownership and dated history.
        Object.assign(existing, { realm: record.realm, s: record.s, site: record.site, src: record.src, srcs: [...record.srcs], chk: record.chk, foundation: true });
        existing.al = [...new Set([...(existing.al || []), ...record.al])];
        if (!existing.hq) existing.hq = record.hq;
        if (!existing.yr) existing.yr = record.yr;
        if (!existing.vet) existing.vet = record.vet;
      } else players.push({ ...record, al: [...record.al], srcs: [...record.srcs] });
    });
    return players;
  }
  window.ppCompanyFoundation = { records, merge };
})();