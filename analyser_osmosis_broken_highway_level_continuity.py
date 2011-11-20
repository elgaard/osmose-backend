#!/usr/bin/env python
#-*- coding: utf-8 -*-

###########################################################################
##                                                                       ##
## Copyrights Frédéric Rodrigo 2011                                      ##
##                                                                       ##
## This program is free software: you can redistribute it and/or modify  ##
## it under the terms of the GNU General Public License as published by  ##
## the Free Software Foundation, either version 3 of the License, or     ##
## (at your option) any later version.                                   ##
##                                                                       ##
## This program is distributed in the hope that it will be useful,       ##
## but WITHOUT ANY WARRANTY; without even the implied warranty of        ##
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         ##
## GNU General Public License for more details.                          ##
##                                                                       ##
## You should have received a copy of the GNU General Public License     ##
## along with this program.  If not, see <http://www.gnu.org/licenses/>. ##
##                                                                       ##
###########################################################################

import sys, re, popen2, urllib, time
from pyPgSQL import PgSQL
from modules import OsmSax
from modules import OsmOsis

###########################################################################

sql10 = """
CREATE OR REPLACE FUNCTION ends(nodes bigint[]) RETURNS SETOF bigint AS $$
DECLARE BEGIN
    RETURN NEXT nodes[1];
    RETURN NEXT nodes[array_length(nodes,1)];
    RETURN;
END
$$ LANGUAGE plpgsql;

DROP VIEW IF EXISTS network CASCADE;
CREATE VIEW network AS
SELECT
   ways.id,
   ends(ways.nodes) AS nid
FROM
   ways
WHERE
   nodes[1] != nodes[array_length(nodes,1)] AND
   ways.tags?'highway' AND
   ways.tags->'highway' IN ('primary')
;

DROP VIEW IF EXISTS orphan_endin CASCADE;
CREATE VIEW orphan_endin AS
SELECT
    network.id,
    network.nid,
    w1.tags->'highway' IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link') AS endin,
    COUNT(*) AS count
FROM
    network
    JOIN way_nodes AS wn1 ON
        network.nid = wn1.node_id AND
        network.id != wn1.way_id
    JOIN ways AS w1 ON
        wn1.way_id = w1.id AND
        w1.tags?'highway'
GROUP BY
    network.id,
    network.nid,
    w1.tags->'highway' IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link')
;

CREATE TEMP TABLE orphan AS
SELECT
    oai1.*
FROM
    orphan_endin AS oai1
    LEFT JOIN orphan_endin AS oai2 ON
        oai1.id = oai2.id AND
        oai1.nid = oai2.nid AND
        oai2.endin = true
WHERE
    oai1.endin = false AND -- oai1.count >= 1
    oai2.id IS NULL
;
"""

sql11 = """
SELECT
   o1.id,
   ST_X(n1.geom),
   ST_Y(n1.geom)
FROM
   orphan AS o1
   JOIN nodes AS n1 ON
       o1.nid = n1.id,
   orphan AS o2
   JOIN nodes AS n2 ON
       o2.nid = n2.id
WHERE
    o1.nid != o2.nid AND
    ST_DWithin(n1.geom, n2.geom, 1e-2)
GROUP BY
    o1.id,
    n1.geom
;
"""

###########################################################################

def analyser(config, logger = None):

    gisconn = PgSQL.Connection(config.dbs)
    giscurs = gisconn.cursor()
    apiconn = OsmOsis.OsmOsis(config.dbs, config.dbp)

    ## output headers
    outxml = OsmSax.OsmSaxWriter(open(config.dst, "w"), "UTF-8")
    outxml.startDocument()
    outxml.startElement("analyser", {"timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    outxml.startElement("class", {"id":"1", "item":"1120"})
    outxml.Element("classtext", {"lang":"fr", "title":"Continuité rompu du niveau de voie"})
    outxml.Element("classtext", {"lang":"en", "title":"Broken highway level continuity"})
    outxml.endElement("class")

    ## querries
    logger.log(u"requête osmosis")
    giscurs.execute("SET search_path TO %s,public;" % config.dbp)
    giscurs.execute(sql10)
    giscurs.execute(sql11)

    ## output data
    logger.log(u"génération du xml")
    for res in giscurs.fetchall():
        outxml.startElement("error", {"class":"1"})
        outxml.Element("location", {"lat":str(res[2]), "lon":str(res[1])})
        outxml.WayCreate(apiconn.WayGet(res[0]))
        outxml.endElement("error")

    ## output footers
    outxml.endElement("analyser")
    outxml._out.close()