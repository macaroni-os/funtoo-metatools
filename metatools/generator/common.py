def expand_url(url, pkginfo):
    if "version" in pkginfo:
        return url.format(version=pkginfo['version'])
    else:
        return url


def common_init(hub, pkginfo):
    if "src_uri" in pkginfo:
        new_src_uri = []
        if isinstance(pkginfo["src_uri"], list):
            for url in pkginfo["src_uri"]:
                new_src_uri.append(hub.Artifact(url=expand_url(url, pkginfo)))
        elif isinstance(pkginfo["src_uri"], str):
            new_src_uri.append(hub.Artifact(url=expand_url(pkginfo["src_uri"], pkginfo)))
        elif isinstance(pkginfo["src_uri"], dict):
            new_src_uri = {}
            for key in sorted(pkginfo["src_uri"].keys()):
                url_list = pkginfo["src_uri"][key]
                new_src_uri[key] = []
                for url in url_list:
                    new_src_uri[key].append(hub.Artifact(url=expand_url(url, pkginfo)))
        else:
            print("I am confuxed")
            raise TypeError()
        # Allow our default expander to be used:
        pkginfo["artifacts"] = new_src_uri
        del pkginfo["src_uri"]
