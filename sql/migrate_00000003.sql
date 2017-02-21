
ALTER TABLE users ADD PRIMARY KEY (eth_address);
ALTER TABLE users ADD COLUMN payment_address VARCHAR;

UPDATE users SET
  payment_address = subquery.payment_address
  FROM
  (SELECT eth_address, custom->>'payment_address' AS payment_address
   FROM users
   WHERE custom->>'payment_address' IS NOT NULL)
  AS subquery
  WHERE users.eth_address = subquery.eth_address
  ;
