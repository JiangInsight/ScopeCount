

#define main scopecount_bundle_driver
#include "bundles.cpp"
#undef main
#include <numeric>
#include <queue>
#include <random>
#include <set>
#include <sstream>

namespace admission {
using Cost=int64_t;
struct Edge {int to,back;Cost cap;};
class Network {
    vector<vector<Edge>> g;
    vector<int> level,next;
    bool levels(int source,int sink) {
        fill(level.begin(),level.end(),-1);
        queue<int> q;q.push(source);level[source]=0;
        while(!q.empty()){
            int v=q.front();q.pop();
            for(auto e:g[v])if(e.cap>0 && level[e.to]<0){level[e.to]=level[v]+1;q.push(e.to);}
        }
        return level[sink]>=0;
    }
    Cost send(int v,int sink,Cost f){
        if(v==sink)return f;
        for(int &i=next[v];i<(int)g[v].size();++i){
            auto &e=g[v][i];if(e.cap<=0 || level[e.to]!=level[v]+1)continue;
            Cost sent=send(e.to,sink,min(f,e.cap));
            if(sent){e.cap-=sent;g[e.to][e.back].cap+=sent;return sent;}
        }
        return 0;
    }
public:
    explicit Network(int n):g(n),level(n),next(n){}
    void arc(int from,int to,Cost capacity){
        int i=int(g[from].size()),j=int(g[to].size());
        g[from].push_back({to,j,capacity});g[to].push_back({from,i,0});
    }
    Cost flow(int s,int t){
        Cost result=0;
        while(levels(s,t)){
            fill(next.begin(),next.end(),0);
            while(Cost aug=send(s,t,numeric_limits<Cost>::max()/4))result+=aug;
        }return result;
    }


    bool reachable(int v)const{return level[v]>=0;}
};
static U first_bits(int b){return b==64?~U(0):(U(1)<<b)-1;}
template<class F>void each(U x,F f){for(;x;x&=x-1)f(countr_zero(x));}
struct CacheGroup{U members;Cost build;};
struct SharedNode {int node;U plus=0,minus=0;};
struct FixedPlan{
    int b;vector<Cost> add;
    vector<pair<U,Cost>> ranks;
    vector<CacheGroup> cache;
    vector<SharedNode> terms;
    unsigned physical_ranks=0;
    Cost proxy(U keep,Cost H)const{
        Cost result=5*H*Cost(b-popcount(keep));
        each(keep,[&](int j){result+=H*add[j];});
        for(auto [mask,price]:ranks)if(mask&keep)result+=H*price;
        for(auto c:cache)if(c.members&~keep)result+=c.build;
        return result;
    }
    pair<U,Cost> solve(Cost H)const{
        const int src=0,first_rule=1,first_rank=first_rule+b;
        const int first_cache=first_rank+int(ranks.size()),sink=first_cache+int(cache.size());
        Network net(sink+1);


        const Cost inf=1+min(proxy(0,H),proxy(first_bits(b),H));
        for(int j=0;j<b;j++){net.arc(src,first_rule+j,5*H);net.arc(first_rule+j,sink,H*add[j]);}
        for(size_t i=0;i<ranks.size();++i){
            auto [mask,price]=ranks[i];int v=first_rank+int(i);net.arc(v,sink,H*price);
            each(mask,[&](int j){net.arc(first_rule+j,v,inf);});
        }
        for(size_t i=0;i<cache.size();++i){
            auto c=cache[i];int v=first_cache+int(i);net.arc(src,v,c.build);
            each(c.members,[&](int j){net.arc(v,first_rule+j,inf);});
        }
        Cost v=net.flow(src,sink);U keep=0;
        for(int j=0;j<b;j++)if(net.reachable(first_rule+j))keep|=U(1)<<j;
        if(proxy(keep,H)!=v)throw logic_error("Cut witness objective mismatch");
        return {keep,v};
    }
};
FixedPlan compile_terms(const Tree&t,const vector<Q>&q){
    FixedPlan p;p.b=int(q.size());map<int,pair<U,U>> incidence;
    for(int j=0;j<p.b;j++){
        U bit=U(1)<<j;
        for(auto term:frontier(t,{q[j]},false)){
            auto &dst=incidence[term.x];if(term.plus)dst.first|=bit;if(term.minus)dst.second|=bit;
        }
    }
    for(auto [i,m]:incidence)p.terms.push_back({i,m.first,m.second});
    return p;
}
void price_terms(const Tree&t,const vector<Q>&q,FixedPlan&p){
    p.add.assign(p.b,0);map<U,Cost> by_mask;map<pair<U,U>,U> duplicates;
    for(int j=0;j<p.b;j++)duplicates[{q[j].one,q[j].zero}]|=U(1)<<j;
    for(auto term:p.terms){
        if(!term.node)continue;
        const auto &node=t.t[term.node];Cost w=node.w.empty()?2+2*Cost(bit_width(node.p.size())):5;
        U mask=term.plus|term.minus;by_mask[mask]+=w;++p.physical_ranks;
        each(mask,[&](int j){++p.add[j];});
    }
    p.ranks.assign(by_mask.begin(),by_mask.end());
    for(auto [pred,mask]:duplicates){
        int ar=popcount(pred.first|pred.second);
        Cost build=(ar>1 && !(pred.first&pred.second))?((U(t.n)+63)/64)*(ar+3):0;
        p.cache.push_back({mask,build});
    }
}
FixedPlan design(const Tree&t,const vector<Q>&q){
    auto p=compile_terms(t,q);price_terms(t,q,p);return p;
}



class Enumerated {
    vector<Cost> base,per;
public:
    explicit Enumerated(const FixedPlan&p){
        if(p.b>16)return;int k=1<<p.b,all=k-1;
        vector<Cost> dw(k),db(k);
        for(auto [mask,w]:p.ranks)dw[mask]+=w;
        for(auto c:p.cache){db[c.members]+=c.build;}
        for(int j=0;j<p.b;j++)for(int m=0;m<k;m++)if(m&(1<<j)){
            dw[m]+=dw[m^(1<<j)];db[m]+=db[m^(1<<j)];
        }
        base.resize(k);per.resize(k);
        for(int m=0;m<k;m++){
            base[m]=db[all]-db[m];
            per[m]=dw[all]-dw[all^m]+5*(p.b-popcount(unsigned(m)));
            each(m,[&](int j){per[m]+=p.add[j];});
        }
    }
    bool present()const{return !base.empty();}
    pair<U,Cost> solve(Cost h)const{
        Cost best=numeric_limits<Cost>::max();U canonical=0;
        for(size_t m=0;m<base.size();++m){
            Cost z=base[m]+h*per[m];
            if(z<best){best=z;canonical=m;}else if(z==best)canonical&=m;
        }return {canonical,best};
    }
};
static vector<Range> audit_ranges(I n){
    return {{0,0},{0,1},{n,n},{0,n},{I(n/4),I(n-n/3)},{I(n/3),min(n,I(n/3+1))}};
}
static vector<vector<int64_t>> reference_counts(const vector<Q>&q,const vector<U>&rows){
    auto samples=audit_ranges(I(rows.size()));vector<vector<int64_t>> ans(samples.size(),vector<int64_t>(q.size(),0));
    for(size_t i=0;i<samples.size();++i){
        auto s=samples[i];unordered_map<U,I> hist;
        for(I r=s.l;r<s.r;r++)++hist[rows[r]];
        for(auto [x,n]:hist)for(size_t j=0;j<q.size();j++)if((x&q[j].one)==q[j].one && !(x&q[j].zero))ans[i][j]+=n;
    }

    Columns cols(rows);
    for(size_t j=0;j<q.size();++j){
        if(q[j].one&q[j].zero){for(auto &v:ans)if(v[j])throw logic_error("Contradiction");continue;}
        auto bits=cols.cache(q[j]);
        for(size_t i=0;i<samples.size();++i)if(bits.count(samples[i])!=ans[i][j])throw logic_error("Materialized count mismatch");
    }return ans;
}
static void check_answers(const Tree&t,const FixedPlan&p,size_t first,const vector<vector<int64_t>>&expected){
    auto sample=audit_ranges(t.n);
    for(size_t i=0;i<sample.size();i++){auto z=sample[i];vector<int64_t> actual(p.b,0);
        for(auto s:p.terms){auto k=s.node?t.t[s.node].count(z):z.r-z.l;
            each(s.plus,[&](int j){actual[j]+=k;});each(s.minus,[&](int j){actual[j]-=k;});
        }
        for(int j=0;j<p.b;j++)if(actual[j]!=expected[i][first+j])throw logic_error("Fixed plan count mismatch");
    }
}

static vector<U> read_rows(const string&pre){
    ifstream f(pre+".rows",ios::binary|ios::ate);auto len=f.tellg();
    if(len<=0 || U(len)%8 || U(len)/8>=UINT32_MAX)throw runtime_error("Invalid rows "+pre);
    vector<U> r(size_t(len)/8);f.seekg(0);f.read((char*)r.data(),len);if(!f)throw runtime_error("Incomplete rows");return r;
}
static void self_test(){
    std::mt19937_64 rng(471121);int count=0;
    for(int b=1;b<=9;b++)for(int trial=0;trial<40;trial++){
        FixedPlan p;p.b=b;p.add.assign(b,0);
        vector<U> equal(1+trial%b);for(int j=0;j<b;j++)equal[rng()%equal.size()]|=U(1)<<j;
        for(U g:equal)if(g)p.cache.push_back({g,Cost(rng()%80)});
        for(int i=0;i<2*b;i++){
            U mask=rng()&first_bits(b);if(!mask)continue;
            p.ranks.push_back({mask,Cost(rng()%10)});each(mask,[&](int j){p.add[j]++;});
        }
        if(trial==0){p.ranks.clear();fill(p.add.begin(),p.add.end(),5);for(auto& g:p.cache)g.build=0;}
        U previous=first_bits(b);
        for(Cost h:{1,2,3,7,32,4096}){
            Cost best=numeric_limits<Cost>::max();U rule_intersection=first_bits(b);
            for(U m=0;m<=first_bits(b);m++){
                Cost z=p.proxy(m,h);
                if(z<best){best=z;rule_intersection=m;}else if(z==best)rule_intersection&=m;
            }
            auto hit=p.solve(h);
            if(hit!=make_pair(rule_intersection,best) || (hit.first&~previous))throw logic_error("Synthetic exhaustive cut mismatch");
            previous=hit.first;++count;
        }
    }
    cout<<count<<" exhaustive synthetic cuts passed\n";
}


static string stem(const string&pre){size_t i=pre.find_last_of("/\\");return i==string::npos?pre:pre.substr(i+1);}
static void dataset(const string&pre,ostream&out){
    auto rows=read_rows(pre);auto q=readq(pre+".queries");if(q.empty())throw runtime_error("No predicates");
    Tree t(rows);auto expected=reference_counts(q,rows);constexpr int horizons[]={1,4,16,64,256,1024,4096};
    for(int b:{8,16,32,64})for(size_t start=0;start+b<=q.size();start+=b){
        vector<Q> bundle(q.begin()+start,q.begin()+start+b);
        auto p=design(t,bundle);Enumerated oracle(p);U prev=first_bits(b);


        check_answers(t,p,start,expected);
        for(int H:horizons){
            auto before=Clock::now();auto [keep,obj]=p.solve(H);auto dt=elapsed(before);
            if(oracle.present() && oracle.solve(H)!=make_pair(keep,obj))throw logic_error("Exhaustive optimum discrepancy");
            if(keep&~prev)throw logic_error("Non-nested canonical optimum");prev=keep;
            int cache_groups=0;for(auto c:p.cache)cache_groups+=bool(c.members&~keep);
            out<<stem(pre)<<'\t'<<start<<'\t'<<b<<'\t'<<H<<'\t'<<t.n<<'\t'<<t.t.size()<<'\t'<<p.physical_ranks<<'\t'<<p.ranks.size()<<'\t'<<p.cache.size()<<'\t'<<keep<<'\t'<<popcount(keep)<<'\t'<<cache_groups<<'\t'<<obj<<'\t'<<p.proxy(0,H)<<'\t'<<p.proxy(first_bits(b),H)<<'\t'<<int(oracle.present())<<'\t'<<dt<<'\n';
        }
    }
}
}
#ifndef SCOPECUT_LIBRARY
#ifndef SCOPECOUNT_CUT_LIBRARY
int main(int argc,char**argv){
    try{
        if(argc==2 && string(argv[1])=="--self-test"){admission::self_test();return 0;}
        if(argc<3)throw runtime_error("cut.exe --self-test | output.tsv prefix [more prefixes ...]");
        ofstream out(argv[1]);if(!out)throw runtime_error("Cannot create cut log");
        out<<"dataset\tfirst\twidth\thorizon\trows\tnodes\tphysical_ranks\trank_groups\tcache_groups\tkeep_mask\tkept\tcached_groups\tobjective\tall_cache\tall_tree\texhaustive\tsolve_ns\n";
        for(int i=2;i<argc;i++){admission::dataset(argv[i],out);cout<<argv[i]<<'\n';}
        return 0;
    }catch(const exception&e){cerr<<e.what()<<'\n';return 1;}
}
#endif
#endif
