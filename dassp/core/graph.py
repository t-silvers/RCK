from collections import Counter
from copy import deepcopy

import networkx as nx

from core.structures import get_segments_copy_number_profile, get_adjacencies_copy_number_profile
from dassp.core.structures import get_segments_from_genome, get_telomeres_from_genome, strip_phasing_from_adjacencies, strip_haplotype_from_segments, \
    strip_haplotype_from_positions, get_adjacencies_from_genome, assign_ref_adjacency_status, assign_nov_adjacency_status, get_unique_adjacencies, assign_adjacency_status
from dassp.core.structures import Segment, Adjacency, AdjacencyType, HAPLOTYPE, Haplotype

COPY_NUMBER = "copy_number"


def edge_tuple_based_on_flag(u, v, attr, data):
    if data:
        return u, v, attr
    else:
        return u, v


def node_tuple_based_on_flag(n, attr, data):
    if data:
        return n, attr
    return n


class IntervalAdjacencyGraph(object):
    def __init__(self, segments=None, adjacencies=None):
        segments = segments if segments is not None else []
        adjacencies = adjacencies if adjacencies is not None else []
        self.segments = segments
        self.adjacencies = adjacencies
        self.graph = nx.MultiGraph()
        # self.internal_check_consistency()
        # self.build_graph()

    def internal_check_consistency(self):
        self.check_consistency(segments=self.segments, adjacencies=self.adjacencies)

    @classmethod
    def check_consistency(cls, segments, adjacencies, check_ref_adjacencies=True):
        for a in adjacencies:
            if a.adjacency_type == AdjacencyType.NOVEL:
                continue
            elif check_ref_adjacencies:
                p1, p2 = a.position1, a.position2
                if p1.chromosome != p2.chromosome:
                    raise ValueError("Reference adjacency {a} links positions {p1} and {p2} from different chromosomes."
                                     "".format(a=str(a), p1=str(p1), p2=str(p2)))
        segments_extremities = set()
        for s in segments:
            segments_extremities.add(s.start_position)
            segments_extremities.add(s.end_position)
        for a in adjacencies:
            if a.position1 not in segments_extremities or a.position2 not in segments_extremities:
                raise ValueError("Adjacency {a} links positions {p1} and {p2} that do not correspond to segments' extremities positions."
                                 "".format(a=str(a), p1=str(a.position1), p2=str(a.position2)))

    def add_segment_edge(self, segment, sort=True):
        u, v = self.get_edge_vertices_pair_from_segment(segment=segment, sort=sort)
        if self.has_segment_edge(edge=(u, v), sort=sort):
            return
        self.graph.add_edge(u=u, v=v, object=segment)

    def add_adjacency_edge(self, adjacency, sort=True):
        if adjacency.position1 not in self.graph:
            raise ValueError()
        if adjacency.position2 not in self.graph:
            raise ValueError()
        u, v = self.get_edge_vertices_pair_from_adjacency(adjacency=adjacency, sort=sort)
        if self.has_adjacency_edge(edge=(u, v), sort=True):   # can not have parallel adjacency edges. Only possible parallel edges are pairs of segment/adjacency ones
            return
        self.graph.add_edge(u=u, v=v, object=adjacency)

    @staticmethod
    def get_edge_vertices_pair_from_adjacency(adjacency, sort=True):
        u, v = adjacency.position1, adjacency.position2
        if sort:
            u, v = tuple(sorted([u, v]))
        return u, v

    @staticmethod
    def get_edge_vertices_pair_from_segment(segment, sort=True):
        u, v = segment.start_position, segment.end_position
        if sort and segment.is_reversed:
            u, v = v, u
        return u, v

    def build_graph(self):
        for s in self.segments:
            self.add_segment_edge(segment=s)
        for a in self.adjacencies:
            self.add_adjacency_edge(adjacency=a)

    def nodes(self, data=True):
        for n, attr in self.graph.nodes(data=True):
            yield node_tuple_based_on_flag(n=n, attr=attr, data=data)

    def edges(self, data=True, nbunch=None):
        for value in self.graph.edges(nbunch=nbunch, data=data):
            yield value

    def segment_edges(self, data=True, nbunch=None, sort=True):
        for u, v, attr in self.edges(nbunch=nbunch, data=True):
            if isinstance(attr["object"], Segment):
                if sort:
                    u, v = tuple(sorted([u, v]))
                yield edge_tuple_based_on_flag(u, v, attr, data)

    def adjacency_edges(self, data=True, nbunch=None, sort=True):
        for u, v, attr in self.edges(nbunch=nbunch, data=True):
            if isinstance(attr["object"], Adjacency):
                if sort:
                    u, v = tuple(sorted([u, v]))
                yield edge_tuple_based_on_flag(u=u, v=v, attr=attr, data=data)

    def ref_adjacency_edges(self, data=True, nbunch=None, sort=True):
        for u, v, attr in self.adjacency_edges(data=True, nbunch=nbunch, sort=sort):
            if attr["object"].adjacency_type == AdjacencyType.REFERENCE:
                yield edge_tuple_based_on_flag(u=u, v=v, attr=attr, data=data)

    def nov_adjacency_edges(self, data=True, nbunch=None, sort=True):
        for u, v, attr in self.adjacency_edges(data=True, nbunch=nbunch, sort=sort):
            if attr["object"].adjacency_type == AdjacencyType.NOVEL:
                yield edge_tuple_based_on_flag(u=u, v=v, attr=attr, data=data)

    def get_segment_edge(self, node, data=True, sort=True):
        segment_edges = list(self.segment_edges(data=True, nbunch=node, sort=sort))
        if len(segment_edges) != 1:
            raise ValueError()
        u = segment_edges[0][0]
        v = segment_edges[0][1]
        attr = segment_edges[0][2]
        return edge_tuple_based_on_flag(u=u, v=v, attr=attr, data=data)

    def has_segment_edge(self, edge, sort=True):
        u, v = edge
        if sort:
            u, v = tuple(sorted([u, v]))
        if u not in self.graph or v not in self.graph:
            return False
        segment_edges = list(self.segment_edges(data=True, nbunch=u, sort=sort))
        if len(segment_edges) == 0:
            return False
        u_s_edge_data = segment_edges[0][2]
        segment_edges = list(self.segment_edges(data=True, nbunch=v, sort=sort))
        if len(segment_edges) == 0:
            return False
        v_s_edge_data = segment_edges[0][2]
        if u_s_edge_data["object"] != v_s_edge_data["object"]:
            return False
        return True

    @property
    def complies_with_is(self):
        for node in self.nodes(data=False):
            n_as = list(self.nov_adjacency_edges(nbunch=node))
            if len(n_as) > 1:
                return False
        return True

    def adjacency_edges_connected_components_subgraphs(self, ref=True, nov=True, copy=True):
        adjacency_edge_only_iag = self.__class__()
        if ref:
            for u, v, data in self.ref_adjacency_edges(data=True, sort=True):
                adjacency_edge_only_iag.graph.add_edge(u=u, v=v, **data)
        if nov:
            for u, v, data in self.nov_adjacency_edges(data=True, sort=True):
                adjacency_edge_only_iag.graph.add_edge(u=u, v=v, **data)
        for adj_iag_cc in nx.connected_component_subgraphs(G=adjacency_edge_only_iag.graph, copy=copy):
            iag = self.__class__()
            iag.graph = adj_iag_cc
            yield iag

    def ref_adjacency_edges_connected_components_subgraphs(self, copy=True):
        for iag in self.adjacency_edges_connected_components_subgraphs(ref=True, nov=False, copy=copy):
            yield iag

    def nov_adjacency_edges_connected_components_subgraphs(self, copy=True):
        for iag in self.adjacency_edges_connected_components_subgraphs(ref=False, nov=True, copy=copy):
            yield iag

    def get_set_self_segment_edges(self, sort=True):
        result = set()
        for u, v in self.segment_edges(data=False, sort=sort):
            result.add((u, v))
        return result

    def get_set_self_adjacency_edges(self, sort=True):
        result = set()
        for u, v in self.adjacency_edges(data=False, sort=sort):
            result.add((u, v))
        return result

    def intersection_on_segment_edges(self, segments):
        other_edges = set()
        for s in segments:
            u, v = self.get_edge_vertices_pair_from_segment(segment=s, sort=True)
            other_edges.add((u, v))
        return self.get_set_self_segment_edges(sort=True).intersection(other_edges)

    def intersection_on_adjacency_edges(self, adjacencies):
        other_edges = set()
        for a in adjacencies:
            u, v = self.get_edge_vertices_pair_from_adjacency(adjacency=a, sort=True)
            other_edges.add((u, v))
        return self.get_set_self_adjacency_edges(sort=True).intersection(other_edges)

    def relative_complements_on_segment_edges(self, segments):
        self_edges = self.get_set_self_segment_edges(sort=True)
        other_edges = set()
        for s in segments:
            u, v = self.get_edge_vertices_pair_from_segment(segment=s, sort=True)
            other_edges.add((u, v))
        intersection = self_edges.intersection(other_edges)
        self_rel_compl = self_edges - intersection
        other_rel_compl = other_edges - intersection
        return self_rel_compl, other_rel_compl

    def relative_complements_on_adjacency_edges(self, adjacencies):
        self_edges = self.get_set_self_adjacency_edges(sort=True)
        other_edges = set()
        for a in adjacencies:
            u, v = self.get_edge_vertices_pair_from_adjacency(adjacency=a, sort=True)
            other_edges.add((u, v))
        intersection = self_edges.intersection(other_edges)
        self_rel_compl = self_edges - intersection
        other_rel_compl = other_edges - intersection
        return self_rel_compl, other_rel_compl

    def topology_matches_for_genome(self, genome):
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        strip_haplotype_from_segments(segments=segments, inplace=True, strip_positions_haplotypes=True)
        self_rel_compl_segments, genome_rel_compl_segments = self.relative_complements_on_segment_edges(segments=segments)
        if len(self_rel_compl_segments) != 0 or len(genome_rel_compl_segments) != 0:
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        strip_phasing_from_adjacencies(adjacencies=adjacencies, inplace=True, strip_positions_haplotypes=True)
        self_rel_compl_adjs, genome_rel_compl_adjs = self.relative_complements_on_adjacency_edges(adjacencies=adjacencies)
        if len(self_rel_compl_adjs) != 0 or len(genome_rel_compl_adjs) != 0:
            return False
        return True

    def topology_allows_for_genome(self, genome):
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        strip_haplotype_from_segments(segments=segments, inplace=True, strip_positions_haplotypes=True)
        self_rel_compl_segments, genome_rel_compl_segments = self.relative_complements_on_segment_edges(segments=segments)
        if len(genome_rel_compl_segments) != 0:
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        strip_phasing_from_adjacencies(adjacencies=adjacencies, inplace=True, strip_positions_haplotypes=True)
        self_rel_compl_adjs, genome_rel_compl_adjs = self.relative_complements_on_adjacency_edges(adjacencies=adjacencies)
        if len(genome_rel_compl_adjs) != 0:
            return False
        return True

    def represents_given_genome(self, genome):
        if not self.is_copy_number_aware:
            raise ValueError()
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        strip_haplotype_from_segments(segments=segments, inplace=True, strip_positions_haplotypes=True)
        if not self.matches_segment_copy_number_profile(segments):
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        strip_phasing_from_adjacencies(adjacencies=adjacencies, inplace=True, strip_positions_haplotypes=True)
        if not self.matches_adjacency_copy_number_profile(adjacencies):
            return False
        return True

    @property
    def is_copy_number_aware(self):
        for u, v, data in self.edges(data=True):
            if COPY_NUMBER not in data:
                return False
        return True

    @property
    def represents_a_genome(self):
        if not self.is_copy_number_aware:
            return False
        for node in self.graph:
            if not self.has_non_negative_imbalance(node=node):
                return False
        return True

    def node_imbalance(self, node):
        u, v, data = self.get_segment_edge(node=node, data=True, sort=True)
        if COPY_NUMBER not in data:
            raise ValueError()
        segment_copy_number = data[COPY_NUMBER]
        imbalance = segment_copy_number
        for u, v, data in self.adjacency_edges(data=True, nbunch=node, sort=True):
            if COPY_NUMBER not in data:
                raise ValueError()
            adj_copy_number = data[COPY_NUMBER]
            adj_copy_number_multiplier = 2 if u == v else 1
            imbalance -= (adj_copy_number_multiplier * adj_copy_number)
        return imbalance

    def has_non_negative_imbalance(self, node):
        return self.node_imbalance(node=node) >= 0

    def has_positive_imbalance(self, node):
        return self.node_imbalance(node=node) > 0

    def has_zero_imbalance(self, node):
        return self.node_imbalance(node=node) == 0

    def is_telomere(self, node):
        return self.has_positive_imbalance(node=node)

    def is_non_telomere(self, node):
        return self.has_zero_imbalance(node=node)

    def matches_segment_copy_number_profile(self, segments):
        genome_scn_profile = get_segments_copy_number_profile(segments=segments)
        genome_scn_profile_by_edges = {}
        for s, cn in genome_scn_profile.items():
            genome_scn_profile_by_edges[self.get_edge_vertices_pair_from_segment(segment=s, sort=True)] = cn
        self_scn_profile_by_edges = {}
        for u, v, data in self.segment_edges(data=True, sort=True):
            cn = data[COPY_NUMBER]
            self_scn_profile_by_edges[(u, v)] = cn
        checked_edges = set()
        for u, v in genome_scn_profile_by_edges:
            genome_scn = genome_scn_profile_by_edges[(u, v)]
            if (u, v) not in self_scn_profile_by_edges:
                return False
            self_scn = self_scn_profile_by_edges[(u, v)]
            if genome_scn != self_scn:
                return False
            checked_edges.add((u, v))
        for u, v in self_scn_profile_by_edges:
            if (u, v) in checked_edges:
                continue
            if self_scn_profile_by_edges[(u, v)] != 0:
                return False
        return True

    def matches_adjacency_copy_number_profile(self, adjacencies):
        genome_acn_profile = get_adjacencies_copy_number_profile(adjacencies=adjacencies)
        genome_acn_profile_by_edges = {}
        for a, cn in genome_acn_profile.items():
            genome_acn_profile_by_edges[self.get_edge_vertices_pair_from_adjacency(adjacency=a, sort=True)] = cn
        self_acn_profile_by_edges = {}
        for u, v, data in self.adjacency_edges(data=True, sort=True):
            cn = data[COPY_NUMBER]
            self_acn_profile_by_edges[(u, v)] = cn
        checked_edges = set()
        for u, v in genome_acn_profile_by_edges:
            genome_acn = genome_acn_profile_by_edges[(u, v)]
            if (u, v) not in self_acn_profile_by_edges:
                return False
            self_acn = self_acn_profile_by_edges[(u, v)]
            if genome_acn != self_acn:
                return False
            checked_edges.add((u, v))
        for u, v in self_acn_profile_by_edges:
            if (u, v) in checked_edges:
                continue
            if self_acn_profile_by_edges[(u, v)] != 0:
                return False
        return True

    def assign_copy_numbers_from_genome(self, genome, ensure_topology=True, inherit_segment_topology=False, inherit_adjacency_topology=False):
        if ensure_topology and not self.topology_allows_for_genome(genome=genome):
            raise ValueError()
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        strip_haplotype_from_segments(segments=segments, inplace=True, strip_positions_haplotypes=True)
        self.assign_copy_numbers_from_segments(segments=segments, inherit_topology=inherit_segment_topology)
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        strip_phasing_from_adjacencies(adjacencies=adjacencies, inplace=True, strip_positions_haplotypes=True, sort=True)
        self.assign_copy_numbers_from_adjacencies(adjacencies=adjacencies, inherit_topology=inherit_adjacency_topology)

    def assign_copy_numbers_from_segments(self, segments, inherit_topology=False):
        genome_scn_profile = get_segments_copy_number_profile(segments=segments)
        genome_scn_profile_by_edges = {}
        self_segment_edges = self.get_set_self_segment_edges(sort=True)
        processed_segment_edges = set()
        for s, cn in genome_scn_profile.items():
            edge = self.get_edge_vertices_pair_from_segment(segment=s, sort=True)
            u, v = edge
            if edge not in self_segment_edges:
                if inherit_topology:
                    self.add_segment_edge(segment=s, sort=True)
                else:
                    raise ValueError()
            genome_scn_profile_by_edges[edge] = cn
            self.set_segment_edge_copy_number(edge=(u, v), cn=cn, sort=False, soft_miss=False)
            processed_segment_edges.add((u, v))
        for u, v in (self_segment_edges - processed_segment_edges):
            self.set_segment_edge_copy_number(edge=(u, v), cn=0, sort=False, soft_miss=False)

    def assign_copy_numbers_from_adjacencies(self, adjacencies, inherit_topology=False):
        genome_acn_profile = get_adjacencies_copy_number_profile(adjacencies=adjacencies)
        genome_acn_profile_by_edges = {}
        self_adjacency_edges = self.get_set_self_adjacency_edges(sort=True)
        processed_adjacency_edges = set()
        for a, cn in genome_acn_profile.items():
            edge = self.get_edge_vertices_pair_from_adjacency(adjacency=a, sort=True)
            u, v = edge
            if edge not in self_adjacency_edges:
                if inherit_topology:
                    self.add_adjacency_edge(adjacency=a, sort=True)
                else:
                    raise ValueError()
            genome_acn_profile_by_edges[edge] = cn
            self.set_adjacency_edge_copy_number(edge=(u, v), cn=cn, sort=False, soft_miss=False)
            processed_adjacency_edges.add((u, v))
        unprocessed_edges = self_adjacency_edges - processed_adjacency_edges
        for u, v in unprocessed_edges:
            self.set_adjacency_edge_copy_number(edge=(u, v), cn=0, sort=False, soft_miss=False)

    def set_segment_edge_copy_number(self, edge, cn, sort=True, soft_miss=False):
        u, v = edge
        if sort:
            u, v = tuple(sorted([u, v]))
        if not self.has_segment_edge(edge=(u, v), sort=True):
            if soft_miss:
                return
            else:
                raise ValueError()
        u, v, data = self.get_segment_edge(node=u, data=True, sort=True)
        data[COPY_NUMBER] = cn

    def set_adjacency_edge_copy_number(self, edge, cn, sort=True, soft_miss=False):
        u, v = edge
        if sort:
            u, v = tuple(sorted([u, v]))
        if not self.has_adjacency_edge(edge=(u, v), sort=True):
            if soft_miss:
                return
            else:
                raise ValueError()
        u, v, data = self.get_adjacency_edge(edge=(u, v), data=True, sort=True)
        data[COPY_NUMBER] = cn

    def has_adjacency_edge(self, edge, sort=True):
        try:
            self.get_adjacency_edge(edge=edge, data=False, sort=sort)
            return True
        except ValueError:
            return False

    def get_adjacency_edge(self, edge, data=True, sort=True):
        u, v = edge
        if sort:
            u, v = tuple(sorted([u, v]))
        u_adjacency_edges = list(self.adjacency_edges(data=True, nbunch=u, sort=True))
        if len(u_adjacency_edges) == 0:
            raise ValueError()
        v_adjacency_edges = list(self.adjacency_edges(data=True, nbunch=v, sort=True))
        if len(v_adjacency_edges) == 0:
            raise ValueError()
        shared_edge = None
        for uu, uv, uattr in u_adjacency_edges:
            if (uu, uv) != (u, v):
                continue
            for vu, vv, vattr in v_adjacency_edges:
                if (uu, uv) == (vu, vv) and uattr["object"] == vattr["object"]:
                    shared_edge = u, v, uattr
                    break
            if shared_edge is not None:
                break
        if shared_edge is None:
            raise ValueError()
        u, v, attr = shared_edge
        return edge_tuple_based_on_flag(u=u, v=v, attr=attr, data=data)

    def get_telomeres(self, check_cn_awareness=True, sort=True, copy=True):
        if check_cn_awareness and not self.is_copy_number_aware:
            raise ValueError()
        result = []
        for node in self.nodes(data=False):
            if self.is_telomere(node=node):
                if copy:
                    node = deepcopy(node)
                result.append(node)
        if sort:
            result = sorted(result)
        return result


IAG = IntervalAdjacencyGraph


class HaplotypeSpecificIntervalAdjacencyGraph(IntervalAdjacencyGraph):
    def __init__(self, segments=None, adjacencies=None):
        super(HaplotypeSpecificIntervalAdjacencyGraph, self).__init__(segments=segments, adjacencies=adjacencies)

    def add_segment_edge(self, segment, sort=True):
        haplotype = segment.extra[HAPLOTYPE]
        extra = {HAPLOTYPE: haplotype}
        sp = segment.start_position
        ep = segment.end_position
        sp_hs = sp.is_haplotype_specific
        if not sp_hs:
            sp.extra.update(extra)
        ep_hs = ep.is_haplotype_specific
        if not ep_hs:
            ep.extra.update(extra)
        super(HaplotypeSpecificIntervalAdjacencyGraph, self).add_segment_edge(segment=segment, sort=sort)

    def add_adjacency_edge(self, adjacency, sort=True):
        if not adjacency.position1.is_haplotype_specific:
            raise ValueError()
        if not adjacency.position2.is_haplotype_specific:
            raise ValueError()
        super(HaplotypeSpecificIntervalAdjacencyGraph, self).add_adjacency_edge(adjacency=adjacency, sort=sort)

    def build_graph(self):
        for s in self.segments:
            self.add_segment_edge(segment=s)
        for a in self.adjacencies:
            self.add_adjacency_edge(adjacency=a)

    @property
    def complies_with_hiis(self):
        processed_nodes = set()
        for node, attr in self.nodes(data=True):
            n_as = list(self.nov_adjacency_edges(nbunch=node))
            if node in processed_nodes:
                continue
            position = node
            p_haplotype = position.extra[HAPLOTYPE]
            hap_mates = [hap for hap in Haplotype if hap != p_haplotype]
            mate_positions = [deepcopy(position) for _ in hap_mates]
            for p, mh in zip(mate_positions, hap_mates):
                p.extra[HAPLOTYPE] = mh
            for mp in mate_positions:
                if mp in self.graph:
                    n_as.extend(list(self.nov_adjacency_edges(nbunch=mp)))
            if len(n_as) > 1:
                return False
        return True

    @property
    def complies_with_hsis(self):
        return self.complies_with_is

    def topology_matches_for_genome(self, genome):
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        self_rel_compl_segments, genome_rel_compl_segments = self.relative_complements_on_segment_edges(segments=segments)
        if len(self_rel_compl_segments) != 0 or len(genome_rel_compl_segments) != 0:
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        self_rel_compl_adjs, genome_rel_compl_adjs = self.relative_complements_on_adjacency_edges(adjacencies=adjacencies)
        if len(self_rel_compl_adjs) != 0 or len(genome_rel_compl_adjs) != 0:
            return False
        return True

    def topology_allows_for_genome(self, genome):
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        self_rel_compl_segments, genome_rel_compl_segments = self.relative_complements_on_segment_edges(segments=segments)
        if len(genome_rel_compl_segments) != 0:
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        self_rel_compl_adjs, genome_rel_compl_adjs = self.relative_complements_on_adjacency_edges(adjacencies=adjacencies)
        if len(genome_rel_compl_adjs) != 0:
            return False
        return True

    def represents_given_genome(self, genome):
        if not self.is_copy_number_aware:
            raise ValueError()
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        if not self.matches_segment_copy_number_profile(segments):
            return False
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True)
        if not self.matches_adjacency_copy_number_profile(adjacencies):
            return False
        return True

    def assign_copy_numbers_from_genome(self, genome, ensure_topology=True, inherit_segment_topology=False, inherit_adjacency_topology=False):
        if ensure_topology and not self.topology_allows_for_genome(genome=genome):
            raise ValueError()
        segments = get_segments_from_genome(genome=genome, copy=True, make_all_non_reversed=True)
        self.assign_copy_numbers_from_segments(segments=segments, inherit_topology=inherit_segment_topology)
        adjacencies = get_adjacencies_from_genome(genome=genome, copy=True, inherit_haplotypes=True)
        self.assign_copy_numbers_from_adjacencies(adjacencies=adjacencies, inherit_topology=inherit_adjacency_topology)


def construct_iag(ref_genome, mut_genomes, build_graph=True):
    segments = get_segments_from_genome(genome=ref_genome, copy=True)
    ref_adjacencies = get_adjacencies_from_genome(genome=ref_genome, default_adjacency_type=AdjacencyType.REFERENCE)
    nov_adjacencies = []
    for mut_genome in mut_genomes:
        nov_adjacencies.extend(get_adjacencies_from_genome(genome=mut_genome, copy=True))
    nh_ref_adjacencies = strip_phasing_from_adjacencies(adjacencies=ref_adjacencies, inplace=False, strip_positions_haplotypes=True)
    nh_nov_adjacencies = strip_phasing_from_adjacencies(adjacencies=nov_adjacencies, inplace=False, strip_positions_haplotypes=True)
    nh_segments = strip_haplotype_from_segments(segments=segments, inplace=False, strip_positions_haplotypes=True)
    assign_ref_adjacency_status(adjacencies=nh_ref_adjacencies, inplace=True)
    ref_adjacencies_set = set(nh_ref_adjacencies)
    assign_adjacency_status(adjacencies=nh_nov_adjacencies, ref_adjacencies=ref_adjacencies_set, inplace=True)
    nh_nov_adjacencies = [a for a in nh_nov_adjacencies if a.adjacency_type == AdjacencyType.NOVEL]
    unique_nh_ref_adjacencies = get_unique_adjacencies(adjacencies=nh_ref_adjacencies, copy=False)
    unique_nh_nov_adjacencies = get_unique_adjacencies(adjacencies=nh_nov_adjacencies, copy=False)
    result = IntervalAdjacencyGraph(segments=nh_segments, adjacencies=unique_nh_ref_adjacencies + unique_nh_nov_adjacencies)
    if build_graph:
        result.build_graph()
    return result


def construct_hiag(ref_genome, mut_genomes, build_graph=True):
    segments = get_segments_from_genome(genome=ref_genome, copy=True)
    ref_adjacencies = get_adjacencies_from_genome(genome=ref_genome)
    assign_ref_adjacency_status(adjacencies=ref_adjacencies, inplace=True)
    nov_adjacencies = []
    for mut_genome in mut_genomes:
        nov_adjacencies.extend(get_adjacencies_from_genome(genome=mut_genome, copy=True))
    ref_adjacencies_set = set(ref_adjacencies)
    assign_adjacency_status(adjacencies=nov_adjacencies, ref_adjacencies=ref_adjacencies_set, inplace=True)
    nov_adjacencies = [a for a in nov_adjacencies if a.adjacency_type == AdjacencyType.NOVEL]
    unique_ref_adjacencies = get_unique_adjacencies(adjacencies=ref_adjacencies, copy=False)
    unique_nov_adjacencies = get_unique_adjacencies(adjacencies=nov_adjacencies, copy=False)
    result = HaplotypeSpecificIntervalAdjacencyGraph(segments=segments, adjacencies=unique_ref_adjacencies + unique_nov_adjacencies)
    if build_graph:
        result.build_graph()
    return result


HSIAG = HaplotypeSpecificIntervalAdjacencyGraph
HIAG = HSIAG
