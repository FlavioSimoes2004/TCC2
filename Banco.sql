CREATE DATABASE IF NOT EXISTS tcc2;
USE tcc2;

DROP TABLE IF EXISTS dispositivos;
CREATE TABLE dispositivos (
    id int primary key auto_increment,
    mac_address varchar(50) not null,
    ip_address varchar(50) not null,
    status bit(1) default null comment '1 - aprovado, 0 - rejeitado, null - pendente',
    last_checked timestamp default null on update current_timestamp(),
    constraint uq_mac unique (mac_address),
    constraint uq_ip unique (ip_address)
);