# DNS for the host. The hosted zone is READ as a data source — it already exists
# (registered/delegated out of band) and is never created or owned by this config.
# A plain A record points the app subdomain at the host's stable Elastic IP.
data "aws_route53_zone" "primary" {
  name         = var.hosted_zone_name
  private_zone = false
}

# An EIP is a literal IPv4 address, so this is a simple A record (records = [...]),
# not an ALIAS — ALIAS targets are AWS resources (ALB/CloudFront/etc.), not a raw IP.
resource "aws_route53_record" "host" {
  zone_id = data.aws_route53_zone.primary.zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.host.public_ip]
}
